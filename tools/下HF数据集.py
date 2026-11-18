# -*- coding: utf-8 -*-
"""
下载 HuggingFace 数据集（带 token、断点续传）
=========================================================================
为什么要自己写？
-------------------------------------------------------------------------
    huggingface_hub 库要另外装；直接走 HTTP 更可控，
    而且能按文件续传（大文件断了不用重下）。

用法：
    python tools\下HF数据集.py                    下载默认清单
    python tools\下HF数据集.py <repo> [文件...]   指定仓库

token 从环境变量 HF_TOKEN 或 data\hf_token.txt 读。
=========================================================================
"""
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "hf"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}

#: 默认清单：(repo, 文件)
PLAN = [
    ("FreedomIntelligence/Huatuo26M-Lite", ["format_data.jsonl"]),
    ("FreedomIntelligence/huatuo_encyclopedia_qa", ["train_datasets.jsonl"]),
    ("FreedomIntelligence/huatuo_consultation_qa", ["train_datasets.jsonl"]),
]


def token() -> str:
    t = os.environ.get("HF_TOKEN", "").strip()
    if t:
        return t
    p = ROOT / "data" / "hf_token.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def download(repo: str, name: str, tok: str) -> bool:
    dst = OUT / repo.replace("/", "__") / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    url = "https://huggingface.co/datasets/%s/resolve/main/%s" % (repo, name)

    headers = dict(UA)
    if tok:
        headers["Authorization"] = "Bearer " + tok
    have = dst.stat().st_size if dst.exists() else 0
    if have:
        headers["Range"] = "bytes=%d-" % have

    try:
        r = requests.get(url, headers=headers, timeout=120, stream=True, allow_redirects=True)
    except Exception as exc:
        print("  连接失败：%s" % exc)
        return False

    if r.status_code == 416:          # 已经下完
        print("  已有完整文件：%s" % name)
        return True
    if r.status_code not in (200, 206):
        print("  HTTP %s：%s" % (r.status_code, r.text[:120]))
        return False

    mode = "ab" if (have and r.status_code == 206) else "wb"
    total = int(r.headers.get("Content-Length", 0)) + (have if mode == "ab" else 0)
    done = have if mode == "ab" else 0
    t0 = time.time()
    last = 0

    with open(dst, mode) as f:
        for chunk in r.iter_content(1 << 20):
            if not chunk:
                continue
            f.write(chunk)
            done += len(chunk)
            if total and done - last > 200 * 1024 ** 2:
                last = done
                print("    %.1f%%  %.0f/%.0f MB  %.1f MB/s"
                      % (done * 100.0 / total, done / 1024 ** 2, total / 1024 ** 2,
                         done / 1024 ** 2 / max(1e-9, time.time() - t0)))

    print("  完成 %s（%.1f MB，%.0f 秒）" % (name, done / 1024 ** 2, time.time() - t0))
    return True


def main() -> int:
    tok = token()
    print("token：%s" % ("已配置" if tok else "未配置（公开数据集也能下）"))

    plan = PLAN
    if len(sys.argv) > 1:
        repo = sys.argv[1]
        files = sys.argv[2:] or ["train_datasets.jsonl"]
        plan = [(repo, files)]

    for repo, files in plan:
        print("\n== %s" % repo)
        for name in files:
            download(repo, name, tok)

    total = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print("\n总计已下载 %.2f GB，目录 %s" % (total / 1024 ** 3, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
