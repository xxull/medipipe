# -*- coding: utf-8 -*-
"""
从 zip 或目录流式导入 CSV（不解压）
=========================================================================
支持两种输入：
    * 一个 .zip（内部是 .csv / .csv.gz）
    * 一个目录（里面散着 .csv / .csv.gz）

为什么不解压？
-------------------------------------------------------------------------
    解压要额外一份磁盘，之后还得再导一遍。
    这里边读边写 SQLite，磁盘只占最终库那一份。

大表限量
-------------------------------------------------------------------------
    监护/化验这类表动辄几亿行，SQLite 存不下也查不动。
    按表名给上限，取前缀（MIMIC/eICU 都按病人 ID 排序，前缀≈连续病人子集）。

用法
-------------------------------------------------------------------------
    python tools\从zip导入.py --zip <zip或目录> [--prefix miv|eicu] [--max N]
    python tools\从zip导入.py --zip "D:\\...\\EICU 2.0数据" --prefix eicu
"""

import argparse
import csv
import gzip
import io
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"
PREFIX = "miv"
BATCH = 5000

#: 大表行数上限（按文件名小写匹配，MIMIC 和 eICU 都覆盖）
BIG_TABLES = {
    # MIMIC-IV
    "chartevents": 3_000_000,
    "labevents": 3_000_000,
    "emar": 2_000_000,
    "emar_detail": 2_000_000,
    "poe": 2_000_000,
    "prescriptions": 2_000_000,
    "pharmacy": 1_000_000,
    "inputevents": 1_000_000,
    # eICU-CRD
    "nursecharting": 3_000_000,
    "lab": 3_000_000,
    "intakeoutput": 2_000_000,
    "nurseassessment": 2_000_000,
    "nursecare": 1_000_000,
    "physicalexam": 1_000_000,
    "medication": 1_000_000,
    "infusiondrug": 1_000_000,
    "respiratorycare": 500_000,
    "respiratorycharting": 1_000_000,
    "diagnosis": 1_000_000,
    "microbiology": 500_000,
}


def safe(name: str) -> str:
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in str(name))
    return (out.strip("_") or "col").lower()


def open_stream(path: Path):
    """打开 .csv 或 .csv.gz 的文本流。"""
    if path.name.endswith(".gz"):
        return io.TextIOWrapper(
            gzip.open(path, "rb"), encoding="utf-8", errors="replace", newline=""
        )
    return open(path, "r", encoding="utf-8", errors="replace", newline="")


def import_stream(conn: sqlite3.Connection, stream, stem: str, cap: int, t0: float) -> int:
    table = safe(PREFIX + "_" + stem)
    reader = csv.reader(stream)
    try:
        header = next(reader)
    except StopIteration:
        print("  %-30s 空文件，跳过" % stem)
        return 0

    cols, seen = [], {}
    for h in header:
        c = safe(h)
        if c in seen:
            seen[c] += 1
            c = "%s_%d" % (c, seen[c])
        else:
            seen[c] = 0
        cols.append(c)

    conn.execute('DROP TABLE IF EXISTS "%s"' % table)
    conn.execute('CREATE TABLE "%s" (%s)' % (table, ",".join('"%s" TEXT' % c for c in cols)))
    sql = 'INSERT INTO "%s" (%s) VALUES (%s)' % (
        table, ",".join('"%s"' % c for c in cols), ",".join("?" * len(cols)),
    )

    n, truncated, buf = 0, False, []
    for row in reader:
        if len(row) < len(cols):
            row = row + [""] * (len(cols) - len(row))
        buf.append(row[: len(cols)])
        if len(buf) >= BATCH:
            conn.executemany(sql, buf)
            n += len(buf)
            buf.clear()
            if cap and n >= cap:
                truncated = True
                break
    if buf and not truncated:
        conn.executemany(sql, buf)
        n += len(buf)
    conn.commit()

    print("  %-28s → %-26s %9d 行%s | %.0fs"
          % (stem, table, n, "（截断）" if truncated else "", time.time() - t0))
    return n


def main() -> int:
    global PREFIX
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", default=r"D:\BaiduNetdiskDownload\mimic-iv-3.1.zip",
                    help="zip 文件或目录")
    ap.add_argument("--max", type=int, default=0, help="覆盖所有大表的上限")
    ap.add_argument("--only", default="", help="只导这些表，逗号分隔")
    ap.add_argument("--prefix", default="miv", help="表名前缀（eICU 建议 eicu）")
    args = ap.parse_args()
    PREFIX = args.prefix

    src = Path(args.zip)
    if not src.exists():
        print("找不到：%s" % src)
        return 1

    # 收集待处理文件：(打开函数, 名字)
    entries = []
    z = None
    if src.is_dir():
        for p in sorted(src.rglob("*")):
            if p.is_file() and (p.name.endswith(".csv") or p.name.endswith(".csv.gz")):
                entries.append((p.name, p.stat().st_size, p))
    else:
        z = zipfile.ZipFile(src)
        for i in z.infolist():
            if i.filename.endswith(".csv") or i.filename.endswith(".csv.gz"):
                entries.append((Path(i.filename).name, i.file_size, i))

    if args.only:
        want = {x.strip().lower() for x in args.only.split(",") if x.strip()}
        entries = [e for e in entries if e[0].split(".")[0].lower() in want]

    entries.sort(key=lambda e: e[1])          # 小的先导，能早点看到结果

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-200000")

    t0 = time.time()
    total = 0
    print("开始导入 %d 个文件（前缀 %s）\n" % (len(entries), PREFIX))

    for name, _size, obj in entries:
        stem = name.split(".")[0].lower()
        cap = args.max or BIG_TABLES.get(stem, 0)
        try:
            if isinstance(obj, Path):
                stream = open_stream(obj)
            else:
                raw = z.open(obj)
                stream = io.TextIOWrapper(
                    gzip.GzipFile(fileobj=raw), encoding="utf-8", errors="replace", newline=""
                )
            with stream:
                total += import_stream(conn, stream, stem, cap, t0)
        except Exception as exc:
            print("  失败 %s：%s" % (name, str(exc)[:120]))

    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()
    size = DB.stat().st_size / 1024 ** 2
    conn.close()
    if z is not None:
        z.close()

    print("\n完成：%d 行，用时 %.0f 秒，库大小 %.0f MB"
          % (total, time.time() - t0, size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
