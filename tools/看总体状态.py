# -*- coding: utf-8 -*-
"""看整体状态：向量、各数据源表数、库大小、磁盘。"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"

SOURCES = [
    ("MIMIC-IV", "miv_"),
    ("eICU", "eicu_"),
    ("MIMIC-ED", "ed_"),
    ("MIMIC-Note", "note_"),
]


def n_rows(conn, table):
    try:
        return conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
    except sqlite3.Error:
        return 0


def vector_count() -> int:
    """
    向量条数。

    新格式：data/case_ids.jsonl（一行一个 id）+ case_vectors.bin（每行 1024 维 float32）
    老格式：data/case_ids.json（整个数组）
    以前这里只看老格式，导致明明建好了 37 万条向量还显示「还没开始」。
    """
    ids_jsonl = ROOT / "data" / "case_ids.jsonl"
    vec_bin = ROOT / "data" / "case_vectors.bin"
    if ids_jsonl.exists():
        n = 0
        with open(ids_jsonl, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
        # 以 bin 实际能装多少行为准（不匹配时以少的为准）
        if vec_bin.exists() and vec_bin.stat().st_size >= 1024 * 4:
            n = min(n, vec_bin.stat().st_size // (1024 * 4))
        return n
    ids_json = ROOT / "data" / "case_ids.json"
    if ids_json.exists():
        try:
            return len(json.loads(ids_json.read_text(encoding="utf-8")))
        except Exception:
            return 0
    return 0


def main() -> int:
    if not DB.exists():
        print("还没有数据库：%s" % DB)
        print("先跑：python tools\\导入样例数据.py")
        return 0

    conn = sqlite3.connect(str(DB), timeout=30)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    size = DB.stat().st_size
    print("库大小：%.1f GB（%d 张表）" % (size / 1024 ** 3, len(tables)))

    for label, prefix in SOURCES:
        mine = [t for t in tables if t.startswith(prefix)]
        rows = sum(n_rows(conn, t) for t in mine)
        print("  %-10s %2d 张表  %s 行" % (label, len(mine), format(rows, ",")))

    drugs = n_rows(conn, "drugs")
    corpus = n_rows(conn, "case_corpus")
    if "drugs" in tables or "case_corpus" in tables:
        print("  药品 %s 条 | 病例库 %s 个" % (format(drugs, ","), format(corpus, ",")))
    conn.close()

    n = vector_count()
    if n:
        print("\n向量：%s / %s" % (format(n, ","), format(corpus, ",")))
    else:
        print("\n向量：还没开始（跑 tools\\建向量.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
