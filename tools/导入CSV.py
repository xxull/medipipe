# -*- coding: utf-8 -*-
"""
CSV 批量导入（CSV → SQLite）
=========================================================================
把一堆 .csv / .csv.gz 灌进数据库，一个文件一张表。

特点
-------------------------------------------------------------------------
    * 自动建表：列名直接用 CSV 表头
    * 流式读取：大文件也不会把内存吃满
    * 分批提交：中途挂了已完成的部分还在
    * 记录行数：导完能核对

用法
-------------------------------------------------------------------------
    python tools/导入CSV.py <目录> [表名前缀]
    python tools/导入CSV.py data/mimic_demo mimic
"""

import csv
import gzip
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"
BATCH = 2000


def open_csv(path: Path):
    """打开 csv，自动处理 .gz。"""
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def safe_name(name: str) -> str:
    """表名/列名清洗：只留字母数字下划线。"""
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(name))
    return (out.strip("_") or "col").lower()


def import_one(conn: sqlite3.Connection, path: Path, prefix: str) -> int:
    table = safe_name((prefix + "_" if prefix else "") + path.name.split(".")[0])
    with open_csv(path) as fp:
        reader = csv.reader(fp)
        try:
            header = next(reader)
        except StopIteration:
            print("  空文件，跳过：%s" % path.name)
            return 0

        cols = [safe_name(h) for h in header]
        # 去重列名（CSV 偶尔有重复表头）
        seen = {}
        for i, c in enumerate(cols):
            if c in seen:
                seen[c] += 1
                cols[i] = "%s_%d" % (c, seen[c])
            else:
                seen[c] = 0

        conn.execute('DROP TABLE IF EXISTS "%s"' % table)
        conn.execute(
            'CREATE TABLE "%s" (%s)' % (table, ",".join('"%s" TEXT' % c for c in cols))
        )

        placeholders = ",".join("?" * len(cols))
        sql = 'INSERT INTO "%s" (%s) VALUES (%s)' % (
            table, ",".join('"%s"' % c for c in cols), placeholders,
        )

        n = 0
        buf = []
        for row in reader:
            if len(row) < len(cols):
                row = row + [""] * (len(cols) - len(row))
            buf.append(row[: len(cols)])
            if len(buf) >= BATCH:
                conn.executemany(sql, buf)
                n += len(buf)
                buf.clear()
        if buf:
            conn.executemany(sql, buf)
            n += len(buf)
        conn.commit()
    print("  %-32s → 表 %-28s %7d 行 × %d 列" % (path.name, table, n, len(cols)))
    return n


def main() -> int:
    if len(sys.argv) < 2:
        print("用法：python tools/导入CSV.py <目录> [表名前缀]")
        return 2
    src = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else ""
    if not src.exists():
        print("目录不存在：%s" % src)
        return 1

    files = sorted(list(src.glob("*.csv")) + list(src.glob("*.csv.gz")))
    if not files:
        print("目录里没有 csv / csv.gz")
        return 1

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB), timeout=60)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    t0 = time.time()
    total = 0
    for p in files:
        try:
            total += import_one(conn, p, prefix)
        except Exception as exc:
            print("  失败 %s：%s" % (p.name, str(exc)[:100]))

    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    conn.close()

    print("\n完成：%d 个文件，共 %d 行，用时 %.1f 秒" % (len(files), total, time.time() - t0))
    print("库里现有 %d 张表" % len(tables))
    return 0


if __name__ == "__main__":
    sys.exit(main())
