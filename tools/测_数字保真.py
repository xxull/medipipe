# -*- coding: utf-8 -*-
"""验证：翻译不会丢掉原文里的数字（丢了就退回原文）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_翻译  # noqa: E402


def main() -> int:
    ok = True

    cases = [
        ("Sodium Chloride 0.9% Flush", "zh"),   # 之前会被翻成"9%氯化钠"
        ("Vitamin B12 500 mcg", "zh"),
        ("Metformin 500mg tablets", "zh"),
    ]
    for name, target in cases:
        got = b_翻译.batch([name], target).get(name, name)
        nums = b_翻译._numbers(name)
        keep = nums.issubset(b_翻译._numbers(got))
        print("[%s] %-32s → %s（原文数字 %s）"
              % ("PASS" if keep else "FAIL", name[:32], got, sorted(nums)))
        ok = ok and keep

    # 纯中文短语仍应能翻成英文
    en = b_翻译.batch(["胃癌"], "en").get("胃癌", "胃癌")
    good = any(ch.isascii() and ch.isalpha() for ch in en)
    print("[%s] 胃癌 → %s" % ("PASS" if good else "FAIL", en))
    ok = ok and good

    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
