# -*- coding: utf-8 -*-
"""
Framework B · 检索与回答（b_检索）
=========================================================================
从数据库里按关键词捞记录。不预设表结构：扫到哪张表、哪些列就搜哪些。

为什么不用向量检索？
-------------------------------------------------------------------------
    向量检索要先把整个库做一遍嵌入，建索引、存向量，成本不低。
    第一版先用"关键词 + 多列扫描"，数据量到几万条以前完全够用。
    需要更强的时候，这个文件就是唯一要换的地方。
=========================================================================
"""

from __future__ import annotations

# 让"单独运行这个文件"和"被 app_b 导入"都能找到模块
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "framework_b")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def _db_path(db: Optional[str] = None) -> str:
    if db:
        return db
    try:
        from config_配置 import DB_PATH

        return DB_PATH
    except Exception:
        return str(Path(__file__).resolve().parent.parent / "data" / "records.db")


def list_tables(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [r[0] for r in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [r[1] for r in conn.execute('PRAGMA table_info("%s")' % table.replace('"', '""'))]


def estimate_rows(conn: sqlite3.Connection, table: str) -> int:
    """快速估行数（MAX(rowid)，毫秒级；COUNT(*) 在亿级表上要几十秒）。"""
    try:
        return conn.execute(
            'SELECT MAX(rowid) FROM "%s"' % table.replace('"', '""')
        ).fetchone()[0] or 0
    except Exception:
        return 0


#: 单表超过这个行数就默认跳过（LIKE 全表扫描太慢）
MAX_ROWS = 3_000_000

#: 默认搜索范围：真正装"文本"的表。
#: 不默认搜全库是因为 eicu_note（225 万行×7 列）这类表会让一次查询等一分钟，
#: 用户体感就是"搜不到"。
DEFAULT_TABLES = [
    "case_corpus",          # 病例库（诊断+用药+症状文本）
    "huatuo_qa",            # 中文问答
    "drugs",                # 药品
    "miv_d_icd_diagnoses",  # 诊断字典
    "miv_d_icd_procedures",  # 手术字典
    "miv_d_labitems",       # 化验字典
    "miv_d_items",          # 监护项目字典
    "note_discharge",       # 出院小结
    "miv_note_discharge",
    "eicu_admissiondx",     # eICU 入院诊断
    "eicu_diagnosis",       # eICU 诊断
    "miv_d_hcpcs",
]


def search_fts(keyword: str, limit: int = 5, db: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    全文索引检索（搜索引擎式）：BM25 排序，毫秒级。

    索引由 tools\\建搜索索引.py 生成（FTS5 + 中文二元分词）。
    索引不存在时返回空列表，调用方自动退回 LIKE。
    """
    from framework_b.b_分词 import to_query

    kw = (keyword or "").strip()
    query = to_query(kw)
    if not query:
        return []

    path = _db_path(db)
    conn = sqlite3.connect(path, timeout=10)
    try:
        try:
            rows = conn.execute(
                "SELECT src, doc, bm25(search_fts) AS rank FROM search_fts"
                " WHERE search_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []            # 没有索引表

        out: List[Dict[str, Any]] = []
        for src, doc, rank in rows:
            rec = None
            if src == "case_corpus":
                r = conn.execute(
                    "SELECT case_id, source, text, diseases, drugs FROM case_corpus WHERE case_id=?",
                    (doc,)).fetchone()
                if r:
                    rec = {"case_id": r[0], "来源": r[1], "文本": str(r[2])[:400],
                           "诊断": r[3], "用药": r[4]}
            elif src == "huatuo_qa":
                r = conn.execute(
                    "SELECT id, question, answer, label, related_diseases FROM huatuo_qa WHERE 'ht_'||id=?",
                    (doc,)).fetchone()
                if r:
                    rec = {"id": r[0], "科室": r[3], "疾病": r[4],
                           "问": str(r[1])[:300], "答": str(r[2])[:300]}
            elif src == "drugs":
                r = conn.execute(
                    "SELECT id, brand_name, generic_name, indications, quality FROM drugs WHERE 'drug_'||id=?",
                    (doc,)).fetchone()
                if r:
                    rec = {"id": r[0], "brand_name": r[1], "generic_name": r[2],
                           "indications": str(r[3])[:300], "quality": r[4]}
            elif src == "note_discharge":
                hadm = doc.split("_")[1] if "_" in doc else ""
                rec = {"hadm_id": hadm, "文档": doc}
            out.append({"table": src, "score": round(-float(rank), 3), "record": rec or {}})
        return out
    finally:
        conn.close()


def search(
    keyword: str,
    limit: int = 5,
    db: Optional[str] = None,
    min_quality: int = 0,
    only_meta: bool = False,
    max_rows: int = MAX_ROWS,
    all_tables: bool = False,
    tables: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    在库里搜关键词，返回最多 limit 条记录。

    规则：
        * 每张表、每个文本列都试一下 LIKE
        * 命中的字段越多越靠前（简单打分，不做花活）
        * 如果表里有 quality / has_meta 列，就按门槛过滤
        * 默认只搜 DEFAULT_TABLES 里那些"装文本"的表：
          全库搜在 3 亿行的库上要等几分钟，用户会以为坏了
        * all_tables=True 或显式传 tables 时才扩大范围
    """
    kw = (keyword or "").strip()
    path = _db_path(db)
    if not kw or not Path(path).exists():
        return []

    hits: List[Dict[str, Any]] = []
    conn = sqlite3.connect(path, timeout=10)
    try:
        existing = set(list_tables(conn))
        if tables is not None:
            targets = [t for t in tables if t in existing]
        elif all_tables:
            targets = sorted(existing)
        else:
            targets = [t for t in DEFAULT_TABLES if t in existing]
            # 白名单一个都不存在（比如测试用的小库），就退回全表扫描：
            # 这种情况下表通常很小，扫完也是毫秒级。
            if not targets:
                targets = sorted(existing)

        for table in targets:
            if not all_tables and estimate_rows(conn, table) > max_rows:
                continue
            cols = table_columns(conn, table)
            text_cols = [c for c in cols if c not in ("id", "fingerprint", "created_at")]
            if not text_cols:
                continue

            where = " OR ".join('"%s" LIKE ?' % c.replace('"', '""') for c in text_cols)
            params = ["%%%s%%" % kw] * len(text_cols)

            # 质量门槛：只在表里有对应列时生效
            extra = ""
            if min_quality and "quality" in cols:
                extra += ' AND IFNULL("quality",0) >= ?'
                params.append(min_quality)
            if only_meta and "has_meta" in cols:
                extra += ' AND IFNULL("has_meta",0) = 1'
            if extra:
                where = "(" + where + ")" + extra
            try:
                rows = conn.execute(
                    'SELECT %s FROM "%s" WHERE %s LIMIT ?'
                    % (",".join('"%s"' % c.replace('"', '""') for c in cols),
                       table.replace('"', '""'), where),
                    params + [limit * 3],
                ).fetchall()
            except Exception:
                continue

            for row in rows:
                rec = dict(zip(cols, row))
                # 打分：命中几个列
                score = sum(1 for c in text_cols if kw.lower() in str(rec.get(c) or "").lower())
                hits.append({"table": table, "score": score, "record": rec})
    finally:
        conn.close()

    hits.sort(key=lambda x: -x["score"])
    return hits[:limit]


#: FTS5 会生成一批影子表（search_fts_data / _idx / _content / _docsize / _config），
#: 它们不是业务表，统计里要排除，否则"表数"会虚高。
SHADOW_SUFFIX = ("_data", "_idx", "_content", "_docsize", "_config")


def _is_shadow(name: str) -> bool:
    low = name.lower()
    if low.startswith("sqlite_"):
        return True
    # FTS 是索引不是数据：它自身 + 影子表都不该算进"库有多少数据"
    if "fts" in low:
        return True
    return any(low.endswith(s) for s in SHADOW_SUFFIX)


_STATS_CACHE: Dict[str, Any] = {}


def stats(db: Optional[str] = None, ttl: int = 300) -> Dict[str, Any]:
    """带缓存的 stats（界面每刷新一次就统计太浪费）。"""
    path = _db_path(db)
    cached = _STATS_CACHE.get(path)
    now = time.time()
    if cached and now - cached[0] < ttl:
        return cached[1]
    result = _stats_uncached(path)
    _STATS_CACHE[path] = (now, result)
    return result


def _stats_uncached(path: str) -> Dict[str, Any]:
    """
    给自检用：库里有多少表、多少行。

    取数策略（越往后越慢）：
        1. sqlite_stat1 —— ANALYZE 之后 SQLite 自己记的行数，毫秒级
        2. 小表直接 COUNT(*)（50 万行以内）
        3. 都没有就标"估算"，不硬算

    为什么不用 MAX(rowid)？
    -------------------------------------------------------------------
    之前用它估算，算出"2.9 万亿条"——有的表主键就是 rowid，而业务 id 可以
    跳到任意大（导入跳号、删过又插）。MAX(rowid) 是最大 id，不是行数。
    """
    out: Dict[str, Any] = {"db": path, "exists": Path(path).exists(), "tables": {},
                           "total": 0, "exact": True}
    if not out["exists"]:
        return out

    conn = sqlite3.connect(path, timeout=10)
    try:
        tables = [t for t in list_tables(conn) if not _is_shadow(t)]

        # 1. 读 ANALYZE 的统计
        stat1: Dict[str, int] = {}
        try:
            for tbl, stat in conn.execute("SELECT tbl, stat FROM sqlite_stat1"):
                try:
                    stat1[tbl] = int(str(stat).split()[0])
                except Exception:
                    pass
        except Exception:
            # 没跑过 ANALYZE
            pass

        for t in tables:
            n = stat1.get(t)
            if n is None:
                # 2. 没有统计就现算，但只对小表算（>50 万行的表跳过，避免卡住）
                try:
                    approx = conn.execute(
                        "SELECT COUNT(*) FROM (SELECT 1 FROM \"%s\" LIMIT 500001)"
                        % t.replace('"', '""')).fetchone()[0]
                except Exception:
                    approx = 0
                if approx <= 500_000:
                    n = approx
                elif "fts" in t.lower():
                    # 虚拟表（FTS）不进 stat1，但 COUNT 也就零点几秒
                    try:
                        n = conn.execute(
                            'SELECT COUNT(*) FROM "%s"' % t.replace('"', '""')).fetchone()[0]
                    except Exception:
                        n = approx
                else:
                    n = approx        # 500001 是下限，标注为估算
                    out["exact"] = False
            out["tables"][t] = n
            out["total"] += n
    finally:
        conn.close()
    return out


if __name__ == "__main__":
    import json
    import sys

    kw = sys.argv[1] if len(sys.argv) > 1 else ""
    print(json.dumps(stats(), ensure_ascii=False, indent=2))
    if kw:
        print(json.dumps(search(kw, 3), ensure_ascii=False, indent=2)[:800])
