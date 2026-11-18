# -*- coding: utf-8 -*-
"""验证：选了中文之后，药物表确实翻成中文了。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_翻译  # noqa: E402


def main() -> int:
    names = ["Sodium Chloride 0.9% Flush", "Acetaminophen", "Heparin",
             "Ondansetron", "Senna", "Vancomycin"]
    got = b_翻译.batch(names, "zh")
    ok = True
    for n in names:
        v = got.get(n, n)
        translated = v != n
        print("[%s] %-30s → %s" % ("PASS" if translated else "FAIL", n[:30], v))
        ok = ok and translated
    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
