# -*- coding: utf-8 -*-
"""
下载 CMB 中文医学数据集
=========================================================================
CMB = Chinese Medical Benchmark，含考试题 + 临床问答，是文本数据，
正好补我们"纯英文病例"的短板。

来源：https://huggingface.co/datasets/FreedomIntelligence/CMB
（Huatuo-26M 是门控数据集，需要登录授权，暂时跳过）

用法：
    python tools\下CMB.py
"""
import sys
import time
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "cmb"
BASE = "https://huggingface.co/datasets/FreedomIntelligence/CMB/resolve/main/"
FILES = ["CMB-Clin-qa.json", "CMB-datasets.zip"]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dst = OUT / name
        if dst.exists() and dst.stat().st_size > 0:
            print("已有 %s（%.1f MB）" % (name, dst.stat().st_size / 1024 ** 2))
            continue
        url = BASE + name
        print("下载 %s ..." % name)
        t0 = time.time()
        try:
            r = requests.get(url, headers=UA, timeout=300, stream=True)
            r.raise_for_status()
            total = 0
            with open(dst, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        f.write(chunk)
                        total += len(chunk)
            print("  完成 %.1f MB，用时 %.0f 秒" % (total / 1024 ** 2, time.time() - t0))
        except Exception as exc:
            print("  失败：%s" % exc)

    print("\n目录：%s" % OUT)
    for p in sorted(OUT.iterdir()):
        print("  %-28s %8.1f MB" % (p.name, p.stat().st_size / 1024 ** 2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
