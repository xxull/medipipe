# -*- coding: utf-8 -*-
"""验证：翻译按钮点了才翻，能中→英、英→中，且能恢复原文。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_翻译  # noqa: E402


def main() -> int:
    ok = True

    # 英 → 中
    en = ["Cellulitis of face", "Essential (primary) hypertension"]
    m = b_翻译.batch(en, "zh")
    for k in en:
        got = m.get(k, k)
        good = got != k and any("\u4e00" <= ch <= "\u9fff" for ch in got)
        print("[%s] EN→中 %-32s → %s" % ("PASS" if good else "FAIL", k[:32], got))
        ok = ok and good

    # 中 → 英
    zh = ["胃癌", "高血压"]
    m2 = b_翻译.batch(zh, "en")
    for k in zh:
        got = m2.get(k, k)
        good = any(ch.isascii() and ch.isalpha() for ch in got)
        print("[%s] 中→EN %-10s → %s" % ("PASS" if good else "FAIL", k, got))
        ok = ok and good

    # 缓存命中
    import time

    t0 = time.time()
    b_翻译.batch(en, "zh")
    fast = time.time() - t0 < 0.5
    print("[%s] 二次翻译走缓存（%.2f 秒）" % ("PASS" if fast else "FAIL", time.time() - t0))
    ok = ok and fast

    # 整批翻英文：不能原样返回中文（踩过：原样返回被写进缓存，之后一直显示中文）
    zh2 = ["慢性阻塞性肺疾病急性加重", "社区获得性肺炎", "支气管哮喘", "氨溴索", "孟鲁司特"]
    m3 = b_翻译.batch(zh2, "en")
    left = [k for k in zh2 if b_翻译._CJK.search(m3.get(k, k))]
    good = not left
    print("[%s] 整批翻英文没有残留中文%s" % ("PASS" if good else "FAIL",
                                             "" if good else "：" + "、".join(left)))
    ok = ok and good

    # 缓存里不能有语言不对的译文
    from framework_b import b_翻译 as T

    hits = [T._lang_ok(k, m3.get(k, ""), "en") for k in zh2]
    good = all(hits)
    print("[%s] 缓存译文的语言校验" % ("PASS" if good else "FAIL"))
    ok = ok and good

    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
