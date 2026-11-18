# -*- coding: utf-8 -*-
"""
导入开放数据（药品标签 + 医学问答）
=========================================================================
读 data/开放数据/ 下的 JSONL，写进 data/records.db：

    drugs_openfda  →  复用 drugs 表结构，框架 B 的「药品说明」能直接用
    medquad_qa     →  问答表，进全文索引后可关键词检索

同时重建这两张表的全文索引（FTS5 + 二元分词），已有的其它表不动。

用法
-------------------------------------------------------------------------
    python tools\\导入开放数据.py
    python tools\\导入开放数据.py --rebuild   # 先删后导，重来一遍
=========================================================================
"""
import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b.b_分词 import to_index_text  # noqa: E402

DB = ROOT / "data" / "records.db"
OPEN_DIR = ROOT / "data" / "开放数据"
FTS = "search_fts"

#: 这两张表在全文索引里用的 src 名
SRC_DRUG = "drugs"
SRC_QA = "medquad_qa"


def _lines(path: Path):
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                yield json.loads(ln)


def _ensure(conn) -> None:
    # 列对齐“跑药品.py 建的那张表”，不然界面/工具按别的列名查就会报 no such column
    conn.execute(
        "CREATE TABLE IF NOT EXISTS drugs ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " set_id TEXT, brand_name TEXT, generic_name TEXT, manufacturer TEXT,"
        " product_type TEXT, route TEXT, indications TEXT, dosage TEXT, warnings TEXT,"
        " contraindications TEXT, effective_time TEXT, created_at TEXT,"
        " source TEXT, license TEXT, quality INTEGER DEFAULT 80)"
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(drugs)")}
    for col in ("set_id", "brand_name", "generic_name", "manufacturer", "product_type",
                "route", "indications", "dosage", "warnings", "contraindications",
                "effective_time", "created_at", "source", "license", "quality"):
        if col not in cols:
            typ = "INTEGER" if col == "quality" else "TEXT"
            conn.execute("ALTER TABLE drugs ADD COLUMN %s %s" % (col, typ))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS medquad_qa ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " qid TEXT, question TEXT, answer TEXT, focus TEXT, qtype TEXT,"
        " source TEXT, url TEXT, license TEXT)"
    )
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS %s USING fts5("
        " body, src UNINDEXED, doc UNINDEXED, tokenize='unicode61')" % FTS
    )
    conn.commit()


def _clear(conn) -> None:
    """
    只清掉「本来就是这个脚本导进来的」那些行。

    以前是无条件 DELETE FROM drugs，会把用户自己抓的、入库插件写的药全删了。
    """
    conn.execute("DELETE FROM medquad_qa")
    try:
        conn.execute("DELETE FROM drugs WHERE source=? OR license LIKE 'CC0%'",
                     ("openFDA drug label",))
    except sqlite3.Error:
        conn.execute("DELETE FROM drugs")
    for src in (SRC_DRUG, SRC_QA):
        try:
            conn.execute("DELETE FROM %s WHERE src=?" % FTS, (src,))
        except sqlite3.Error:
            pass
    conn.commit()


def load_drugs(conn) -> int:
    rows = list(_lines(OPEN_DIR / "药品_openfda.jsonl"))
    if not rows:
        return 0
    keys = ("set_id", "brand_name", "generic_name", "manufacturer", "product_type",
            "route", "indications", "dosage", "warnings", "contraindications",
            "effective_time", "source", "license")
    conn.executemany(
        "INSERT INTO drugs (%s) VALUES (%s)"
        % (", ".join(keys), ", ".join(":" + k for k in keys)),
        [{k: r.get(k, "") for k in keys} for r in rows],
    )
    conn.commit()
    return len(rows)


def load_qa(conn) -> int:
    rows = list(_lines(OPEN_DIR / "问答_medquad.jsonl"))
    if not rows:
        return 0
    conn.executemany(
        "INSERT INTO medquad_qa (qid, question, answer, focus, qtype, source, url, license)"
        " VALUES (:qid, :question, :answer, :focus, :qtype, :source, :url, :license)",
        [{k: r.get(k, "") for k in ("qid", "question", "answer", "focus", "qtype",
                                    "source", "url", "license")} for r in rows],
    )
    conn.commit()
    return len(rows)


def build_fts(conn) -> int:
    """给这两张表重写全文索引（其它来源保持不动）。"""
    buf = []
    n = 0

    def flush():
        if buf:
            conn.executemany("INSERT INTO %s(body, src, doc) VALUES (?,?,?)" % FTS, buf)
            buf.clear()

    for did, brand, generic, ind, dos, warn in conn.execute(
        "SELECT id, IFNULL(brand_name,''), IFNULL(generic_name,''),"
        " IFNULL(indications,''), IFNULL(dosage,''), IFNULL(warnings,'') FROM drugs"
    ):
        body = to_index_text(" ".join([brand, generic, ind, dos, warn])[:4000])
        if body:
            buf.append((body, SRC_DRUG, "drug_%s" % did))
            n += 1
        if len(buf) >= 2000:
            flush()

    for qid, focus, q, a in conn.execute(
        "SELECT id, IFNULL(focus,''), IFNULL(question,''), IFNULL(answer,'') FROM medquad_qa"
    ):
        body = to_index_text((focus + " " + q + " " + a)[:4000])
        if body:
            buf.append((body, SRC_QA, "qa_%s" % qid))
            n += 1
        if len(buf) >= 2000:
            flush()

    flush()
    conn.commit()
    try:
        conn.execute("INSERT INTO %s(%s) VALUES('optimize')" % (FTS, FTS))
        conn.commit()
    except sqlite3.Error:
        pass
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    conn = sqlite3.connect(str(db), timeout=120)
    try:
        _ensure(conn)
        if args.rebuild:
            _clear(conn)
        nd = load_drugs(conn)
        nq = load_qa(conn)
        nf = build_fts(conn)
    finally:
        conn.close()

    print("药品：%d 条" % nd)
    print("问答：%d 条" % nq)
    print("全文索引：%d 条（%s / %s）" % (nf, SRC_DRUG, SRC_QA))
    print("库：%s  用时 %.1f 秒" % (db, time.time() - t0))
    if not nd and not nq:
        print("没找到 data/开放数据/*.jsonl，先跑 python tools\\下载开放数据.py")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
