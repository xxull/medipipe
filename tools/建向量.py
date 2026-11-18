# -*- coding: utf-8 -*-
"""
给病例做向量（bge-m3）—— 追加写入版
=========================================================================
存储格式
-------------------------------------------------------------------------
    data/case_vectors.bin     float32 矩阵，每行 1024 维，**只追加**
    data/case_ids.jsonl       每行一个 case_id，与 bin 的行一一对应

为什么不用 .npy？
-------------------------------------------------------------------------
    .npy 要整文件重写。37 万条时是 1.5 GB，每 500 条重写一次，
    磁盘被打满，Web 页面读文件都被拖到 99 秒。

    改成纯追加之后，每次只写新算的那几百条，开销可以忽略。

断点续跑
-------------------------------------------------------------------------
    行数 = case_ids.jsonl 的行数；如果 bin 比它长/短，自动截断对齐。

用法：
    python tools\建向量.py            # 补齐所有缺的
    python tools\建向量.py 5000       # 只做前 5000 条里缺的
=========================================================================
"""
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = DATA / "records.db"
VEC = DATA / "case_vectors.bin"
IDS = DATA / "case_ids.jsonl"
LOCK = DATA / ".vector_build.lock"
MODEL = "bge-m3:latest"
URL = "http://127.0.0.1:11434/api/embeddings"
DIM = 1024


def embed(text: str) -> list:
    import urllib.request

    payload = json.dumps({"model": MODEL, "prompt": text[:1200]}).encode("utf-8")
    req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))["embedding"]
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def load_done() -> list:
    """读已完成列表，并对齐 bin 的长度。"""
    if not IDS.exists():
        return []
    ids = [x.strip() for x in IDS.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not VEC.exists():
        return []
    size = VEC.stat().st_size
    want = len(ids) * DIM * 4
    if size != want:
        # bin 多半是写到一半被杀；截到能对齐的整数行
        keep = min(size, want) // (DIM * 4)
        with open(VEC, "r+b") as f:
            f.truncate(keep * DIM * 4)
        ids = ids[:keep]
        IDS.write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
        print("  对齐：bin 截断到 %d 行" % keep)
    return ids


def append_vecs(vecs: list, ids: list) -> None:
    """追加写：只写新算的这批，不碰已有数据。"""
    if not vecs:
        return
    arr = np.asarray(vecs, dtype=np.float32)
    with open(VEC, "ab") as f:
        f.write(arr.tobytes())
    with open(IDS, "a", encoding="utf-8") as f:
        f.write("\n".join(ids) + "\n")


def acquire_lock() -> bool:
    try:
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not acquire_lock():
        print("已有建向量进程在跑。确认没有的话，删掉 %s" % LOCK.name)
        return 1

    try:
        return _run(limit)
    finally:
        try:
            LOCK.unlink()
        except OSError:
            pass


def _run(limit: int) -> int:
    conn = sqlite3.connect(str(DB), timeout=120)
    rows = conn.execute(
        "SELECT case_id, text FROM case_corpus ORDER BY case_id"
        + (" LIMIT %d" % limit if limit else "")
    ).fetchall()
    if limit:
        half = max(1, limit // 2)
        picked = []
        for src in ("mimic", "eicu", "huatuo"):
            picked += conn.execute(
                "SELECT case_id, text FROM case_corpus WHERE source=? ORDER BY case_id LIMIT ?",
                (src, half // 3 + 1),
            ).fetchall()
        rows = picked
    conn.close()

    if not rows:
        print("case_corpus 是空的")
        return 1

    done = set(load_done())
    todo = [(cid, text) for cid, text in rows if cid not in done]
    print("总病例 %d，已有向量 %d，本次要处理 %d" % (len(rows), len(done), len(todo)))
    if not todo:
        print("全部已处理完")
        return 0

    t0 = time.time()
    batch_vecs, batch_ids = [], []
    for i, (cid, text) in enumerate(todo, start=1):
        try:
            batch_vecs.append(embed(text))
            batch_ids.append(cid)
        except Exception as exc:
            print("  跳过 %s：%s" % (cid, str(exc)[:60]))
            continue

        if len(batch_vecs) >= 500:
            append_vecs(batch_vecs, batch_ids)
            batch_vecs, batch_ids = [], []
            rate = i / max(1e-9, time.time() - t0)
            print("  %d/%d  %.0f 条/秒  预计还要 %.0f 分钟"
                  % (i, len(todo), rate, (len(todo) - i) / max(0.1, rate) / 60))

    append_vecs(batch_vecs, batch_ids)
    total = len(done) + len(todo)
    print("\n完成：累计 %d 条，用时 %.0f 秒" % (total, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
