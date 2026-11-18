# -*- coding: utf-8 -*-
"""
预热翻译：把常见病名/药名提前翻好，存进缓存
=========================================================================
为什么需要？
-------------------------------------------------------------------------
    qwen3-vl 是**思考模型**：每次调用要先"想"十几秒才输出译文。
    换成非思考模型（qwen2.5:3b）后一个词约 0.2 秒，翻 10 个名字也要 2 秒。

    但这些词是**固定集合**（病情库里的诊断名、药品名）。
    提前跑一遍存进 translate_cache，之后查表就是 0 秒。

跑多少
-------------------------------------------------------------------------
    默认按出现频次取前 1500 个诊断名 + 前 500 个药名。
    实测 qwen2.5:3b 约 1.5 秒/批（8 个词），1500 个名字 3 分钟跑完。

用法
-------------------------------------------------------------------------
    python tools\\预热翻译.py              # 默认量
    python tools\\预热翻译.py 3000 1000    # 病名 3000 + 药名 1000
    python tools\\预热翻译.py --stats      # 只看进度
=========================================================================
"""
import json
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_翻译  # noqa: E402

DB = ROOT / "data" / "records.db"
BATCH = 10


def top_diseases(limit: int):
    c = sqlite3.connect(str(DB), timeout=120)
    counter = Counter()
    for (dj,) in c.execute("SELECT diseases FROM case_corpus"):
        try:
            for d in json.loads(dj or "[]"):
                if d and len(str(d)) > 1:
                    counter[str(d)] += 1
        except Exception:
            pass
    c.close()
    return [d for d, _n in counter.most_common(limit)]


def top_drugs(limit: int):
    c = sqlite3.connect(str(DB), timeout=120)
    rows = [r[0] for r in c.execute(
        "SELECT brand_name FROM drugs WHERE IFNULL(brand_name,'')<>'' LIMIT ?", (limit,))]
    c.close()
    return rows


def stats() -> int:
    c = sqlite3.connect(str(DB), timeout=60)
    n = c.execute("SELECT COUNT(*) FROM translate_cache").fetchone()[0]
    c.close()
    print("缓存已有 %d 条译文" % n)
    return 0


def main() -> int:
    if "--stats" in sys.argv:
        return stats()

    nd = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
    ng = int(sys.argv[2]) if len(sys.argv) > 2 else 500

    if not b_翻译.preflight():
        print("本地模型没启动：先运行 ollama serve")
        return 1

    names = top_diseases(nd) + top_drugs(ng)
    # 去重 + 只留需要翻的
    names = list(dict.fromkeys(n for n in names if n and not b_翻译._already_in(n, "zh")))
    print("待预热 %d 个词（病名 %d + 药名 %d）" % (len(names), nd, ng), flush=True)

    t0 = time.time()
    done = 0
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        t1 = time.time()
        b_翻译.batch(chunk, "zh")
        done += len(chunk)
        if (i // BATCH) % 5 == 0:
            rate = done / max(1e-9, time.time() - t0)
            left = (len(names) - done) / max(0.1, rate) / 60
            print("  %d/%d  %.1f 秒/批  预计还要 %.0f 分钟"
                  % (done, len(names), time.time() - t1, left), flush=True)

    print("\n完成：%d 个词，用时 %.0f 分钟" % (done, (time.time() - t0) / 60))
    return stats()


if __name__ == "__main__":
    sys.exit(main())
