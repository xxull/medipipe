# -*- coding: utf-8 -*-
"""
把 dayi 抓到的词条并进全文索引（增量，不重建）
=========================================================================
为什么不重建？
-------------------------------------------------------------------------
    重建要把 93 万条重新切词写一遍，7 分钟；这里只需追加 3 万多条。

用法：
    python tools\并入dayi索引.py
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
BATCH = 2000


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")

    # 先清掉上次并入的 dayi 文档（按 src 删，FTS5 支持 DELETE）
    try:
        conn.execute("DELETE FROM search_fts WHERE src='dayi'")
        conn.commit()
    except Exception as exc:
        print("清理旧数据失败（可能表还不存在）：%s" % exc)

    rows = conn.execute(
        "SELECT url, type, title, text, fields FROM dayi_pages"
    ).fetchall()
    print("dayi 词条：%d 条" % len(rows))

    t0 = time.time()
    buf = []
    n = 0
    for url, typ, title, text, fields in rows:
        body = to_index_text("%s %s %s" % (title or "", text or "", fields or ""))
        if not body:
            continue
        buf.append((body, "dayi", url))
        n += 1
        if len(buf) >= BATCH:
            conn.executemany(
                "INSERT INTO search_fts(body, src, doc) VALUES (?,?,?)", buf)
            buf.clear()
    if buf:
        conn.executemany("INSERT INTO search_fts(body, src, doc) VALUES (?,?,?)", buf)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM search_fts").fetchone()[0]
    conn.close()
    print("并入 %d 条，索引现有 %d 条，用时 %.0f 秒" % (n, total, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
