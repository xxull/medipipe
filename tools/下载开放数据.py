# -*- coding: utf-8 -*-
"""
下载免费开放的医疗数据（可直接随仓库分发）
=========================================================================
抓两样东西，都允许再分发：

1. openFDA 药品标签        https://open.fda.gov
   许可：公共领域 / CC0 1.0（FDA 官方声明）
   内容：品牌名、通用名、厂商、适应症、用法用量、警示、给药途径

2. MedQuAD 医学问答        https://github.com/abachaa/MedQuAD
   许可：CC BY 4.0（需署名）
   内容：47,457 条问答，来自 12 个 NIH 网站（CancerGov / NIDDK / CDC …）

都不需要 API Key。抓完写成 JSONL，放到 data/开放数据/。

用法
-------------------------------------------------------------------------
    python tools\\下载开放数据.py                 # 默认 1000 药品 + 3000 问答
    python tools\\下载开放数据.py --openfda 2000 --medquad 5000
    python tools\\下载开放数据.py --only medquad
=========================================================================
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "开放数据"

UA = "medipipe-open-data/1.0 (+https://github.com/; contact: local user)"

OPENFDA = "https://api.fda.gov/drug/label.json"
MEDQUAD_API = "https://api.github.com/repos/abachaa/MedQuAD/contents/%s?ref=master"
MEDQUAD_RAW = "https://raw.githubusercontent.com/abachaa/MedQuAD/master/%s"

#: MedQuAD 里挑几个覆盖面广的目录
MEDQUAD_DIRS = [
    "1_CancerGov_QA",      # 肿瘤
    "5_NIDDK_QA",          # 消化/肾/内分泌
    "6_NINDS_QA",          # 神经
    "9_CDC_QA",            # 感染/公共卫生
    "10_MPlus_ADAM_QA",    # 综合（MedlinePlus）
]


def _get(url: str, timeout: int = 30, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as exc:          # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("下载失败 %s：%s" % (url, last))


def _json(url: str, **kw):
    return json.loads(_get(url, **kw).decode("utf-8", "replace"))


def _short(text, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s[:n]


# ---------------------------------------------------------------- openFDA
def fetch_openfda(want: int) -> int:
    """按页抓 openFDA 药品标签，只要带适应症的。"""
    path = OUT / "药品_openfda.jsonl"
    got = 0
    skip = 0
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        while got < want:
            n = min(100, want - got)
            url = "%s?search=_exists_:openfda.brand_name&limit=%d&skip=%d" % (OPENFDA, n, skip)
            try:
                data = _json(url)
            except Exception as exc:  # noqa: BLE001
                print("  openFDA 第 %d 页失败：%s" % (skip // 100 + 1, str(exc)[:80]))
                break
            rows = data.get("results") or []
            if not rows:
                break
            for r in rows:
                of = r.get("openfda") or {}
                brand = (of.get("brand_name") or [""])[0]
                generic = (of.get("generic_name") or [""])[0]
                manu = (of.get("manufacturer_name") or [""])[0]
                route = (of.get("route") or [""])[0]
                indications = _short((r.get("indications_and_usage") or [""])[0], 800)
                if not (brand or generic) or not indications:
                    continue
                f.write(json.dumps({
                    "brand_name": brand,
                    "generic_name": generic,
                    "manufacturer": manu,
                    "product_type": (of.get("product_type") or [""])[0],
                    "route": route,
                    "indications": indications,
                    "dosage": _short((r.get("dosage_and_administration") or [""])[0], 400),
                    "warnings": _short((r.get("warnings") or r.get("warnings_and_cautions") or [""])[0], 400),
                    "contraindications": _short((r.get("contraindications") or [""])[0], 300),
                    "effective_time": r.get("effective_time", ""),
                    "set_id": r.get("set_id", ""),
                    "source": "openFDA drug label",
                    "license": "CC0-1.0（美国公共领域）",
                    "url": "https://open.fda.gov/apis/drug/label/",
                }, ensure_ascii=False) + "\n")
                got += 1
            skip += n
            print("  openFDA：%d/%d" % (got, want))
            time.sleep(0.2)
            if len(rows) < n:
                break
    tmp.replace(path)
    print("药品 → %s（%d 条）" % (path, got))
    return got


# ---------------------------------------------------------------- MedQuAD
def _medquad_files(folder: str) -> list:
    try:
        items = _json(MEDQUAD_API % urllib.parse.quote(folder))
    except Exception as exc:  # noqa: BLE001
        print("  列目录失败 %s：%s" % (folder, str(exc)[:80]))
        return []
    return [it["name"] for it in items if it.get("name", "").endswith(".xml")]


def _parse_medquad(xml_bytes: bytes, folder: str) -> list:
    """解析一份 MedQuAD XML，取出问答对。"""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    url = root.get("url", "")
    source = root.get("source", folder.split("_", 1)[-1])
    focus = (root.findtext("Focus") or "").strip()
    out = []
    for pair in root.iter("QAPair"):
        q = (pair.findtext("Question") or "").strip()
        a = _short(pair.findtext("Answer") or "", 1200)
        if not q or not a:
            continue
        qel = pair.find("Question")
        out.append({
            "qid": pair.get("pid", ""),
            "question": q,
            "answer": a,
            "focus": focus,
            "qtype": (qel.get("qtype") if qel is not None else "") or "",
            "source": source,
            "url": url,
            "license": "CC BY 4.0（署名：MedQuAD, Ben Abacha & Demner-Fushman, 2019）",
        })
    return out


def fetch_medquad(want: int) -> int:
    """从几个目录里按顺序抓 XML，攒够问答就停。"""
    path = OUT / "问答_medquad.jsonl"
    got = 0
    files = 0
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for folder in MEDQUAD_DIRS:
            if got >= want:
                break
            names = _medquad_files(folder)
            print("  %s：%d 个文件" % (folder, len(names)))
            for name in names:
                if got >= want:
                    break
                try:
                    raw = _get(MEDQUAD_RAW % urllib.parse.quote("%s/%s" % (folder, name)))
                except Exception as exc:  # noqa: BLE001
                    print("    跳过 %s：%s" % (name, str(exc)[:60]))
                    continue
                files += 1
                for row in _parse_medquad(raw, folder):
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    got += 1
                    if got >= want:
                        break
                time.sleep(0.05)
            print("  MedQuAD：%d/%d（已下 %d 个文件）" % (got, want, files))
    tmp.replace(path)
    print("问答 → %s（%d 条，来自 %d 个 XML）" % (path, got, files))
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--openfda", type=int, default=1000)
    ap.add_argument("--medquad", type=int, default=3000)
    ap.add_argument("--only", choices=["openfda", "medquad"], default=None)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    if args.only in (None, "openfda"):
        total += fetch_openfda(args.openfda)
    if args.only in (None, "medquad"):
        total += fetch_medquad(args.medquad)

    for p in sorted(OUT.glob("*.jsonl")):
        print("  %-24s %6.1f KB" % (p.name, p.stat().st_size / 1024))
    print("合计 %d 条" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
