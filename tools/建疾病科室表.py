# -*- coding: utf-8 -*-
"""
从 Huatuo 问答里学"疾病 → 科室"（disease_dept）
=========================================================================
为什么不用手写规则？
-------------------------------------------------------------------------
    我手写的关键词只能覆盖常见词。Huatuo 有 17.7 万条真实问答，
    每条都带**科室标注**（妇产科/内科/肿瘤科…）。

    把"疾病名 → 科室"统计出来，比关键词规则准得多：
        related_diseases=胃癌, label=肿瘤科  →  胃癌 归肿瘤科（用真实标注投票）

用法：
    python tools\建疾病科室表.py
=========================================================================
"""
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"
TABLE = "disease_dept"


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")

    rows = conn.execute(
        "SELECT related_diseases, label FROM huatuo_qa"
        " WHERE IFNULL(related_diseases,'')<>'' AND IFNULL(label,'')<>''"
    ).fetchall()
    print("参与统计的问答：%d 条" % len(rows))

    votes = defaultdict(Counter)
    for diseases, label in rows:
        for d in re.split(r"[,，、;；|/]", str(diseases)):
            d = d.strip()
            if 1 < len(d) <= 40:
                votes[d][label] += 1

    conn.execute(
        "CREATE TABLE IF NOT EXISTS %s (disease TEXT PRIMARY KEY, dept TEXT, votes INTEGER)" % TABLE
    )
    conn.execute("DELETE FROM %s" % TABLE)

    payload = []
    for d, c in votes.items():
        dept, n = c.most_common(1)[0]
        payload.append((d, dept, n))
    conn.executemany("INSERT OR REPLACE INTO %s VALUES (?,?,?)" % TABLE, payload)
    conn.commit()

    print("疾病数：%d" % len(payload))
    print("\n科室分布（按疾病数）：")
    for dept, n in conn.execute(
        "SELECT dept, COUNT(*) FROM %s GROUP BY dept ORDER BY 2 DESC LIMIT 12" % TABLE
    ):
        print("  %-14s %5d" % (dept, n))
    print("\n样例：")
    for d, dept, v in conn.execute(
        "SELECT disease, dept, votes FROM %s ORDER BY votes DESC LIMIT 8" % TABLE
    ):
        print("  %-16s → %-12s（%d 票）" % (d, dept, v))
    conn.close()
    print("\n完成，用时 %.0f 秒" % (time.time() - time.time()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
