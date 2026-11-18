# -*- coding: utf-8 -*-
"""看 eICU 导入进度。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"
PREFIX = sys.argv[1] if len(sys.argv) > 1 else "eicu"


def main() -> int:
    if not DB.exists():
        print("库不存在")
        return 1
    conn = sqlite3.connect(str(DB), timeout=60)
    pat = PREFIX + "_%"
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ? ORDER BY name",
        (pat,),
    )]
    rows = []
    for t in tables:
        try:
            rows.append((conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0], t))
        except Exception:
            pass
    rows.sort(reverse=True)
    print("%s 已建表：%d 张" % (PREFIX, len(tables)))
    for n, t in rows[:12]:
        print("  %-32s %9d" % (t, n))
    print("总行数：%d" % sum(n for n, _ in rows))
    print("库大小：%.1f GB" % (DB.stat().st_size / 1024 ** 3))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
