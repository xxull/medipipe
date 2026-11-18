# -*- coding: utf-8 -*-
"""
导出可公开分发的样例数据（不涉及任何有版权/协议限制的数据）
=========================================================================
做三份：
    药品样例.jsonl   ← openFDA（美国公共领域），100 条高质量记录
    病例样例.jsonl   ← 合成病例，204 条（已存在）
    症状样例.jsonl   ← 从 dayi 症状词条里抽「标题 + 一句话说明」

为什么只放这些？
-------------------------------------------------------------------------
    MIMIC/eICU 协议禁止再分发；dayi 的内容有版权。
    样例只用来"跑通流程"，真实数据由使用者自己按 README 获取。
=========================================================================
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"
OUT = ROOT / "data" / "样例数据"


def export_drugs(n: int = 100) -> int:
    c = sqlite3.connect(str(DB), timeout=60)
    rows = c.execute(
        "SELECT brand_name, generic_name, manufacturer, indications, dosage, warnings, route"
        " FROM drugs WHERE IFNULL(quality,0)>=70 AND IFNULL(indications,'')<>''"
        " ORDER BY quality DESC LIMIT ?", (n,)
    ).fetchall()
    c.close()
    path = OUT / "药品样例.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "brand_name": r[0], "generic_name": r[1], "manufacturer": r[2],
                "indications": (r[3] or "")[:500], "dosage": (r[4] or "")[:300],
                "warnings": (r[5] or "")[:300], "route": r[6],
                "source": "openFDA（公共领域）",
            }, ensure_ascii=False) + "\n")
    print("药品样例：%d 条 → %s" % (len(rows), path))
    return len(rows)


def export_symptoms(n: int = 300) -> int:
    c = sqlite3.connect(str(DB), timeout=60)
    rows = c.execute(
        "SELECT title, text FROM dayi_pages WHERE type='symptom' LIMIT ?", (n,)
    ).fetchall()
    c.close()
    path = OUT / "症状样例.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for title, text in rows:
            # 只取一段简述，避免整段搬运（版权考虑）
            brief = re.sub(r"\s+", " ", text or "")[:120]
            f.write(json.dumps({"symptom": title, "brief": brief}, ensure_ascii=False) + "\n")
    print("症状样例：%d 条 → %s（仅标题+简短说明，供演示）" % (len(rows), path))
    return len(rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    export_drugs(100)
    export_symptoms(300)
    for p in sorted(OUT.glob("*.jsonl")):
        print("  %-18s %6.1f KB" % (p.name, p.stat().st_size / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
