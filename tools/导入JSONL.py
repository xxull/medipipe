# -*- coding: utf-8 -*-
"""
导入 JSONL（一行一个 JSON）到 SQLite
=========================================================================
适用：Huatuo 系列数据集（format_data.jsonl / train_datasets.jsonl）

特点：
    * 自动展平嵌套字段（list/dict 转成字符串）
    * 一列一名，缺字段留空
    * 分批提交，中途可断

用法：
    python tools\导入JSONL.py <文件> <表名> [最多行数]
=========================================================================
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"
BATCH = 2000


def flat_value(v):
    """把任意值转成字符串（列表用 | 拼，字典转 JSON）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, (list, tuple)):
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(json.dumps(x, ensure_ascii=False))
            else:
                parts.append(str(x))
        return " | ".join(parts)
    return json.dumps(v, ensure_ascii=False)


def main() -> int:
    if len(sys.argv) < 3:
        print("用法：python tools\\导入JSONL.py <文件> <表名> [最多行数]")
        return 2
    src = Path(sys.argv[1])
    table = "".join(c if (c.isalnum() or c == "_") else "_" for c in sys.argv[2]).lower()
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    if not src.exists():
        print("找不到文件：%s" % src)
        return 1

    conn = sqlite3.connect(str(DB), timeout=120)
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute('DROP TABLE IF EXISTS "%s"' % table)

    created = False
    cols = []
    n = 0
    buf = []
    t0 = time.time()

    with open(src, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue

            if not created:
                cols = [("".join(c if (c.isalnum() or c == "_") else "_" for c in k)).lower()
                        for k in obj.keys()]
                conn.execute('CREATE TABLE "%s" (%s)' % (
                    table, ",".join('"%s" TEXT' % c for c in cols)))
                created = True

            row = []
            for k in obj.keys():
                row.append(flat_value(obj.get(k)))
            # 列数对齐（后面出现的额外字段丢掉）
            row = (row + [""] * len(cols))[:len(cols)]
            buf.append(row)

            if len(buf) >= BATCH:
                conn.executemany('INSERT INTO "%s" VALUES (%s)'
                                 % (table, ",".join("?" * len(cols))), buf)
                n += len(buf)
                buf.clear()
                if n % 20000 == 0:
                    print("  %d 行  %.0fs" % (n, time.time() - t0))
                if limit and n >= limit:
                    break

    if buf:
        conn.executemany('INSERT INTO "%s" VALUES (%s)'
                         % (table, ",".join("?" * len(cols))), buf)
        n += len(buf)
    conn.commit()
    conn.close()

    print("完成：%s → 表 %s，%d 行 × %d 列，用时 %.0f 秒"
          % (src.name, table, n, len(cols), time.time() - t0))
    print("列：", ", ".join(cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
