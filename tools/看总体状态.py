# -*- coding: utf-8 -*-
"""看整体状态：向量、各数据源表数、库大小、磁盘。"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=120)
    print("库大小：%.1f GB" % (DB.stat().st_size / 1024 ** 3))

    # 先 ANALYZE：SQLite 把每张表的行数记进 sqlite_stat1，
    # 之后统计是毫秒级，不用对亿级表跑 COUNT(*)（那样要几十秒）
    conn.execute("ANALYZE")
    conn.commit()

    groups = {"miv_": "MIMIC-IV", "eicu_": "eICU", "ed_": "MIMIC-ED", "note_": "MIMIC-Note"}
    for prefix, label in groups.items():
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", (prefix + "%",))]
        rows = 0
        for t in tables:
            try:
                rows += conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            except Exception:
                pass
        print("  %-10s %2d 张表  %s 行" % (label, len(tables), format(rows, ",")))

    drugs = conn.execute("SELECT COUNT(*) FROM drugs").fetchone()[0]
    corpus = conn.execute("SELECT COUNT(*) FROM case_corpus").fetchone()[0]
    print("  药品 %s 条 | 病例库 %s 个" % (format(drugs, ","), format(corpus, ",")))
    conn.close()

    ids = ROOT / "data" / "case_ids.json"
    try:
        n = len(json.loads(ids.read_text(encoding="utf-8")))
        print("\n向量：%s / %s" % (format(n, ","), format(corpus, ",")))
    except Exception:
        print("\n向量：还没开始")
    return 0


if __name__ == "__main__":
    sys.exit(main())
