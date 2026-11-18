# -*- coding: utf-8 -*-
"""
建全文检索索引（FTS5 + 二元分词）
=========================================================================
思路（照搬搜索引擎）
-------------------------------------------------------------------------
    1. 把每张表的文本切词（中文二元、英文单词）
    2. 写进 FTS5 倒排表（BM25 排序内置）
    3. 查询时同样切词，MATCH + bm25() 排序

索引哪些表
-------------------------------------------------------------------------
    case_corpus   病例库（诊断+用药+症状）
    huatuo_qa     中文问答
    drugs         药品
    note_discharge 出院小结

用法
-------------------------------------------------------------------------
    python tools\建搜索索引.py            # 全量重建
    python tools\建搜索索引.py --stats    # 只看现状
=========================================================================
"""
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b.b_分词 import to_index_text  # noqa: E402

DB = ROOT / "data" / "records.db"
FTS = "search_fts"
BATCH = 2000

#: (表名, 取文本的 SQL, 文档 ID 表达式)
SOURCES = [
    ("case_corpus",
     "SELECT case_id, text FROM case_corpus WHERE text IS NOT NULL AND text<>''"),
    ("huatuo_qa",
     """SELECT 'ht_'||id, IFNULL(question,'') || ' ' || IFNULL(answer,'')
        || ' ' || IFNULL(related_diseases,'') || ' ' || IFNULL(label,'')
        FROM huatuo_qa"""),
    ("drugs",
     """SELECT 'drug_'||id,
        IFNULL(brand_name,'')||' '||IFNULL(generic_name,'')||' '
        ||IFNULL(manufacturer,'')||' '||IFNULL(indications,'')
        ||' '||IFNULL(dosage,'')||' '||IFNULL(warnings,'')
        FROM drugs"""),
    ("note_discharge",
     "SELECT 'note_'||hadm_id||'_'||rowid, text FROM note_discharge WHERE text IS NOT NULL"),
]


def reset(conn) -> None:
    conn.execute('DROP TABLE IF EXISTS %s' % FTS)
    conn.execute(
        "CREATE VIRTUAL TABLE %s USING fts5(body, src UNINDEXED, doc UNINDEXED,"
        " tokenize='unicode61')" % FTS
    )
    conn.commit()


def build(conn) -> int:
    total = 0
    t0 = time.time()
    for src, sql in SOURCES:
        try:
            cur = conn.execute(sql)
        except Exception as exc:
            print("  跳过 %s：%s" % (src, str(exc)[:60]))
            continue

        print("  %s 建索引中…" % src)
        buf = []
        n = 0
        while True:
            rows = cur.fetchmany(5000)
            if not rows:
                break
            for doc_id, text in rows:
                body = to_index_text(str(text)[:4000])
                if not body:
                    continue
                buf.append((body, src, str(doc_id)))
                n += 1
            if len(buf) >= BATCH:
                conn.executemany("INSERT INTO %s(body, src, doc) VALUES (?,?,?)" % FTS, buf)
                buf.clear()
        if buf:
            conn.executemany("INSERT INTO %s(body, src, doc) VALUES (?,?,?)" % FTS, buf)
        conn.commit()
        total += n
        print("    %s：%d 条，累计 %d 条，%.0f 秒" % (src, n, total, time.time() - t0))

    conn.execute("INSERT INTO %s(%s) VALUES('optimize')" % (FTS, FTS))
    conn.commit()
    return total


def main() -> int:
    if "--stats" in sys.argv:
        c = sqlite3.connect(str(DB))
        try:
            n = c.execute("SELECT COUNT(*) FROM %s" % FTS).fetchone()[0]
            print("索引条数：%d" % n)
            for src, n2 in c.execute("SELECT src, COUNT(*) FROM %s GROUP BY src" % FTS):
                print("  %-16s %d" % (src, n2))
        except Exception as exc:
            print("索引不存在：%s" % exc)
        return 0

    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")
    reset(conn)
    t0 = time.time()
    n = build(conn)
    size = DB.stat().st_size / 1024 ** 3
    conn.close()
    print("\n完成：%d 条索引，用时 %.0f 秒，库 %.1f GB" % (n, time.time() - t0, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
