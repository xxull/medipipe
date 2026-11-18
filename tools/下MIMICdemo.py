# -*- coding: utf-8 -*-
"""
列出 / 下载 MIMIC-IV demo。
=========================================================================
demo 是开放访问的（不需要签 DUA），100 个病人，体积很小，
用来把"CSV → 数据库 → 查询"这条链路跑通正合适。

用法：
    python tools/下MIMICdemo.py list     只列文件
    python tools/下MIMICdemo.py get      全部下载到 data/mimic_demo/
"""

import re
import sys
import time
from pathlib import Path

import requests

BASE = "https://physionet.org/files/mimic-iv-demo/2.2/"
OUT = Path(__file__).resolve().parent.parent / "data" / "mimic_demo"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}


def list_files() -> list:
    """递归找目录里的 csv.gz（demo 分 hosp/ 和 icu/ 两个子目录）。"""
    found = []

    def scan(url: str):
        try:
            r = requests.get(url, headers=UA, timeout=30)
        except Exception as exc:
            print("  打不开 %s：%s" % (url, exc))
            return
        if r.status_code != 200:
            print("  %s 返回 %s" % (url, r.status_code))
            return

        for name in re.findall(r'href="([^"/?]+\.csv\.gz)"', r.text):
            found.append(url + name)
        for sub in re.findall(r'href="([a-zA-Z0-9_]+)/"', r.text):
            if sub in ("hosp", "icu", "ed"):
                scan(url + sub + "/")

    scan(BASE)
    return found


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    files = list_files()
    print("找到 %d 个文件" % len(files))

    if cmd == "list":
        for f in files:
            print("  " + f.replace(BASE, ""))
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    t0 = time.time()
    for url in files:
        name = url.replace(BASE, "").replace("/", "_")
        dst = OUT / name
        if dst.exists() and dst.stat().st_size > 0:
            print("  已有 %s" % name)
            continue
        try:
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            dst.write_bytes(r.content)
            total += len(r.content)
            print("  下载 %-40s %8.1f KB" % (name, len(r.content) / 1024))
        except Exception as exc:
            print("  失败 %s：%s" % (name, exc))
        time.sleep(0.2)

    print("\n完成：%d 个文件，共 %.1f MB，用时 %.0f 秒"
          % (len(list(OUT.glob('*.csv.gz'))), total / 1024 / 1024, time.time() - t0))
    print("目录：", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
