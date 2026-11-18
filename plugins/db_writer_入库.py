# -*- coding: utf-8 -*-
"""
入库插件（db_writer）
=========================================================================
把上一步抽出来的结构化字段写进 SQLite 数据库。

为什么用 SQLite？
    单文件、不用装服务、几千上万条随便跑，以后想迁 PostgreSQL 也只要改这一处。

四个设计要点
-------------------------------------------------------------------------
【1】表结构自动长出来
    第一次入库时按字段建表；以后再冒出**新字段**，自动 ALTER TABLE 补列。
    所以不需要提前设计表 —— 插件返回什么字段，库里就有什么列。

【2】按内容去重
    对"字段内容"算一个指纹（sha1），存成 UNIQUE 列。
    同一条数据跑两次不会插两遍（批量跑重复链接时特别重要）。

【3】不吞异常
    写库失败就抛出来，页面上会红牌 + 中文解释，不会假装成功。

【4】留一行原始信息
    除了字段，还记 source（来源，比如网址）、brief、created_at，
    以后能追到"这条数据从哪来的"。

输入
-------------------------------------------------------------------------
    ctx["upstream"]  上一步返回的 dict（没有就尝试把 ctx["text"] 当 JSON 解析）
输出
-------------------------------------------------------------------------
    {"inserted": 新增条数, "skipped": 跳过条数, "table": 表名, "db": 路径}
=========================================================================
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from typing import Any, Dict, List

from base_基类 import BasePlugin

#: 默认库文件（放项目 data/ 下，跟着项目走）
# 默认库位置从配置读（环境变量 FW_DB 可覆盖）
try:
    import sys as _sys

    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config_配置 import DB_PATH as _CFG_DB, DB_TABLE as _CFG_TABLE

    DEFAULT_DB = _CFG_DB
    DEFAULT_TABLE = _CFG_TABLE
except Exception:
    DEFAULT_DB = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "records.db"
    )
    DEFAULT_TABLE = "records"

#: 默认表名
#: 这些键不当业务字段入库（内部信息）
SKIP_KEYS = {"method", "paid", "missing", "error", "text", "output", "content", "result"}


class DBWriter(BasePlugin):
    """把结构化结果写进数据库。"""

    name = "入库"
    NEEDS = {"network": False, "model": False}
    OUTPUT_FIELDS = ["inserted", "skipped", "table"]

    def __init__(self) -> None:
        super().__init__()
        #: 上一次是不是"只存了原文"（没拿到结构化字段）
        self._fallback_note = False

    def execute(self, text_data: str) -> str:
        """单文本接口：能当 JSON 就当字段存，不能就当原文存。"""
        payload = None
        try:
            candidate = json.loads(text_data)
            if isinstance(candidate, dict):
                payload = candidate
        except Exception:
            payload = None

        if payload is None:
            payload = {"text": str(text_data)[:4000]}
            self._fallback_note = True
        result = self._write(payload, source="", brief="")
        return "已入库 %d 条，跳过重复 %d 条（表 %s）" % (
            result["inserted"], result["skipped"], result["table"]
        )

    def execute_rich(self, ctx: dict) -> dict:
        # 优先用上一步的结构化产出
        data: Dict[str, Any] = {}
        upstream = ctx.get("upstream")
        if isinstance(upstream, dict) and upstream:
            data = upstream
        else:
            # 没有就试试把 text 当 JSON
            text = (ctx.get("text") or "").strip()
            if text.startswith("{"):
                try:
                    data = json.loads(text)
                except Exception:
                    data = {}
        if not data:
            # 上游只给了纯文本 → 别直接报错，把原文存进 text 列
            # （"抓取 → 入库"这种最简链路也应该能用）
            text = (ctx.get("text") or "").strip()
            if not text:
                raise RuntimeError("入库插件没收到任何内容：上一步没有产出")
            data = {"text": text[:4000]}
            # 记一句提示，让用户知道存的是原文而不是字段
            self._fallback_note = True

        source = self._guess_source(ctx)
        brief = (ctx.get("brief") or "")[:200]
        return self._write(data, source=source, brief=brief)

    @staticmethod
    def _guess_source(ctx: dict) -> str:
        """
        猜"这条数据从哪来"，方便以后追溯。

        顺序：线上注释 → 原文里的"来源：…" → 原文里的第一个 http 链接
        """
        import re

        note = (ctx.get("note") or "").strip()
        if note:
            return note[:300]

        # 用户直接给的输入（最常见：一个网址）
        raw_input = str(ctx.get("input") or "").strip()
        if re.match(r"^https?://\S+$", raw_input):
            return raw_input[:300]

        original = str(ctx.get("original") or "")
        m = re.search(r"(?m)^\s*来源[:：]\s*(\S+)", original)
        if m:
            return m.group(1).strip(" \"',，")[:300]

        # 严格一点：URL 到引号/尖括号/空白就结束，
        # 否则抓到 JSON 里的 \"https://x/\", 这种会把尾巴带进来
        m = re.search(r"https?://[^\s\"'<>\\]+", original)
        if m:
            return m.group(0).rstrip(".,;，。；)）]】")[:300]
        return ""

    # ------------------------------------------------------------------
    # 具体实现
    # ------------------------------------------------------------------
    def _fields_of(self, data: Dict[str, Any]) -> List[str]:
        keys = [k for k in data.keys() if k not in SKIP_KEYS]
        # 只有原文没字段时，"text" 本身就是唯一要存的东西
        if not keys and "text" in data:
            keys = ["text"]
        return keys

    @staticmethod
    def _to_text(value: Any) -> str:
        """列表拼成一行，其余转字符串。"""
        if isinstance(value, (list, tuple)):
            return "、".join(str(v) for v in value)
        if value is None:
            return ""
        return str(value)

    def _fingerprint(self, data: Dict[str, Any], fields: List[str]) -> str:
        """按字段内容算指纹，用来去重（同内容只存一份）。"""
        norm = "|".join("%s=%s" % (k, self._to_text(data.get(k)).strip()) for k in sorted(fields))
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()

    def _open(self, db_path: str) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @staticmethod
    def _quote(name: str) -> str:
        """给列名加双引号，避免字段名里带空格/中文关键字炸掉。"""
        return '"%s"' % str(name).replace('"', '""')

    def _ensure_table(self, conn: sqlite3.Connection, table: str, fields: List[str]) -> None:
        """建表；缺列就补（老库升级也能用）。"""
        conn.execute(
            'CREATE TABLE IF NOT EXISTS %s ('
            "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "  fingerprint TEXT UNIQUE,"
            "  source TEXT,"
            "  brief TEXT,"
            "  created_at TEXT"
            ")" % self._quote(table)
        )
        existing = {row[1] for row in conn.execute("PRAGMA table_info(%s)" % self._quote(table))}
        for f in fields:
            if f not in existing:
                # 新字段 → 加一列（TEXT 够用，以后要类型再迁移）
                conn.execute("ALTER TABLE %s ADD COLUMN %s TEXT" % (self._quote(table), self._quote(f)))

    def _write(self, data: Dict[str, Any], source: str, brief: str) -> Dict[str, Any]:
        # 允许通过备注临时换库/换表：
        #   brief 里写 "db=D:\x.db table=demo" 就用那个（不写就用默认）
        db_path, table = DEFAULT_DB, DEFAULT_TABLE
        for token in (brief or "").replace("；", " ").split():
            if token.startswith("db="):
                db_path = token[3:]
            elif token.startswith("table="):
                table = token[6:]

        fields = self._fields_of(data)
        if not fields:
            raise RuntimeError("上一步返回的字段全是内部字段（method/paid 之类），没有可入库的内容")

        conn = self._open(db_path)
        try:
            self._ensure_table(conn, table, fields)

            fp = self._fingerprint(data, fields)
            exists = conn.execute(
                "SELECT 1 FROM %s WHERE fingerprint = ?" % self._quote(table), (fp,)
            ).fetchone()
            if exists:
                return {"inserted": 0, "skipped": 1, "table": table, "db": db_path}

            cols = ["fingerprint", "source", "brief", "created_at"] + fields
            values = [fp, source, brief, time.strftime("%Y-%m-%d %H:%M:%S")] + [
                self._to_text(data.get(f)) for f in fields
            ]
            placeholders = ",".join("?" * len(cols))
            conn.execute(
                "INSERT INTO %s (%s) VALUES (%s)"
                % (self._quote(table), ",".join(self._quote(c) for c in cols), placeholders),
                values,
            )
            conn.commit()
            return {"inserted": 1, "skipped": 0, "table": table, "db": db_path}
        finally:
            conn.close()


# -------------------------------------------------------------------------
# 自测：python plugins/db_writer_入库.py
# -------------------------------------------------------------------------
if __name__ == "__main__":
    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), "db_writer_demo.db")
    ctx = {
        "upstream": {"chief_complaint": "咳嗽三天", "duration": "3 天", "medications": ["布洛芬 200mg"]},
        "brief": "db=%s table=demo" % tmp,
        "note": "https://example.com/a",
    }
    w = DBWriter()
    print("第一次:", w.execute_rich(ctx))
    print("第二次（应跳过）:", w.execute_rich(ctx))

    conn = sqlite3.connect(tmp)
    for row in conn.execute("SELECT id, chief_complaint, duration, medications, source FROM demo"):
        print("库里:", row)
    conn.close()
