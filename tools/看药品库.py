# -*- coding: utf-8 -*-
"""看药品库质量：字段填充率、来源分布、样例。"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"
T = "drugs"


def main() -> int:
    c = sqlite3.connect(str(DB))

    def q(sql, *args):
        return c.execute(sql, args).fetchone()[0]

    def filled(col):
        return q('SELECT COUNT(*) FROM "%s" WHERE IFNULL("%s","")<>""' % (T, col))

    total = q('SELECT COUNT(*) FROM "%s"' % T)
    print("药品库：%d 条\n" % total)
    print("字段填充率：")
    for col in ("generic_name", "brand_name", "manufacturer", "product_type",
                "route", "indications", "dosage", "warnings"):
        n = filled(col)
        print("  %-16s %5d  %5.1f%%" % (col, n, n * 100.0 / max(1, total)))

    print("\n不同通用名：%d" % q('SELECT COUNT(DISTINCT generic_name) FROM "%s"' % T))
    print("不同厂商：%d" % q('SELECT COUNT(DISTINCT manufacturer) FROM "%s"' % T))

    print("\n产品类型分布：")
    for row in c.execute(
        'SELECT IFNULL(NULLIF(product_type,""),"(空)") p, COUNT(*) n FROM "%s"'
        ' GROUP BY p ORDER BY n DESC LIMIT 5' % T
    ):
        print("  %-26s %d" % (row[0], row[1]))

    print("\n最新 3 条：")
    for row in c.execute(
        'SELECT brand_name, generic_name, indications FROM "%s" ORDER BY id DESC LIMIT 3' % T
    ):
        print("  %-26s | %-20s | %s" % ((row[0] or "")[:26], (row[1] or "")[:20], (row[2] or "")[:46]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
