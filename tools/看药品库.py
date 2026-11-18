# -*- coding: utf-8 -*-
"""看药品库质量：字段填充率、来源分布、样例。

`drugs` 表可能是不同脚本建的（跑药品.py / 导入开放数据.py / 入库插件），
列不一定齐全，所以先看实际有哪些列，缺的跳过，不直接报错。
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"
T = "drugs"

#: 关心这些列（按重要性排）
WANT = ["generic_name", "brand_name", "manufacturer", "product_type",
        "route", "indications", "dosage", "warnings"]


def main() -> int:
    if not DB.exists():
        print("还没有数据库：%s\n先跑 tools/导入样例数据.py 或 tools/导入开放数据.py" % DB)
        return 0

    c = sqlite3.connect(str(DB))
    cols = [r[1] for r in c.execute('PRAGMA table_info("%s")' % T)]
    if not cols:
        print("库里没有 %s 表（先导入药品数据）" % T)
        return 0

    def q(sql, *args):
        return c.execute(sql, args).fetchone()[0]

    total = q('SELECT COUNT(*) FROM "%s"' % T)
    print("药品库：%d 条" % total)
    print("列：%s\n" % ", ".join(cols))

    print("字段填充率：")
    for col in WANT:
        if col not in cols:
            print("  %-16s   （表里没这一列，跳过）" % col)
            continue
        n = q('SELECT COUNT(*) FROM "%s" WHERE IFNULL("%s","")<>""' % (T, col))
        print("  %-16s %5d  %5.1f%%" % (col, n, n * 100.0 / max(1, total)))

    for label, col in (("不同通用名", "generic_name"), ("不同厂商", "manufacturer")):
        if col in cols:
            print("\n%s：%d" % (label, q('SELECT COUNT(DISTINCT "%s") FROM "%s"' % (col, T))))

    if "product_type" in cols:
        print("\n产品类型分布：")
        for row in c.execute(
            'SELECT IFNULL(NULLIF(product_type,""),"(空)") p, COUNT(*) n FROM "%s"'
            ' GROUP BY p ORDER BY n DESC LIMIT 5' % T
        ):
            print("  %-26s %d" % (row[0], row[1]))

    print("\n最新 3 条：")
    pick = [x for x in ("brand_name", "generic_name", "indications") if x in cols]
    order = "id" if "id" in cols else "rowid"
    for row in c.execute(
        'SELECT %s FROM "%s" ORDER BY %s DESC LIMIT 3'
        % (", ".join('IFNULL("%s","")' % x for x in pick), T, order)
    ):
        vals = list(row) + [""] * (3 - len(row))
        print("  %-26s | %-20s | %s" % (str(vals[0])[:26], str(vals[1])[:20], str(vals[2])[:46]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
