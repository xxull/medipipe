# -*- coding: utf-8 -*-
"""检查详情查询用到的索引，缺的就补上（这是最直接的性能优化）。"""
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"

#: (表, 列, 建立这条索引的理由)
NEED = [
    ("note_discharge", "hadm_id", "点开病例要取出院小结，没索引就全表扫 33 万行"),
    ("huatuo_qa", "id", "点开中文问答病例要按 id 查，没索引全表扫 17 万行"),
    ("case_corpus", "case_id", "相似检索取病例详情"),
    ("miv_admissions", "hadm_id", "点开 MIMIC 病例要读住院信息"),
]


def existing(conn, table: str) -> set:
    cols = set()
    # PRAGMA index_list 返回多列（seq, name, unique, origin, partial），不能按单值解包
    for row in conn.execute('PRAGMA index_list("%s")' % table):
        name = row[1]
        for info in conn.execute('PRAGMA index_info("%s")' % name):
            cols.add(info[2])
    return cols


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")

    for table, col, why in NEED:
        try:
            cols = existing(conn, table)
        except Exception as exc:
            print("跳过 %s：%s" % (table, exc))
            continue
        if col in cols:
            print("%-18s %-10s 已有索引" % (table, col))
            continue
        t0 = time.time()
        conn.execute('CREATE INDEX IF NOT EXISTS "idx_%s_%s" ON "%s"("%s")'
                     % (table, col, table, col))
        conn.commit()
        print("%-18s %-10s 建好（%.1f 秒）— %s" % (table, col, time.time() - t0, why))

    conn.execute("ANALYZE")
    conn.commit()
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
