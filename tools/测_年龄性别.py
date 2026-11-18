# -*- coding: utf-8 -*-
"""
回归：年龄段 / 性别筛选不能报 no such column
=========================================================================
踩过的坑
-------------------------------------------------------------------------
    公开版用例库是「导入样例数据.py」建的，早期那张表没有 gender 列，
    于是界面上只要选了性别就抛 sqlite3.OperationalError: no such column，
    整页红字。

    现在两头都兜住了：
      * 导入脚本建表时保证有 dept / age / age_band / gender
      * b_相似 查不到这列时，返回一句能看懂的话（提示跑补字段脚本），不崩

用法
-------------------------------------------------------------------------
    python tools\\测_年龄性别.py
=========================================================================
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_相似  # noqa: E402

CASES = [
    ("胸部", "吸烟20年", "咳嗽咳痰、发热三天", "18-44", "男"),
    ("胸部", "", "咳嗽咳痰", "65+", "女"),
    ("腹部", "", "上腹痛、反酸", "", ""),
    ("胸部", "", "咳嗽", "", "男"),
    ("", "", "头痛、眩晕", "45-64", ""),
]


def main() -> int:
    ok = True
    for where, hist, how, band, gender in CASES:
        try:
            r = b_相似.find_similar(where, hist, how, top_k=10, master=None,
                                    age_band=band, gender=gender)
        except Exception as exc:  # noqa: BLE001
            print("[FAIL] 年龄=%s 性别=%s 抛异常：%s" % (band or "全部", gender or "全部", exc))
            ok = False
            continue

        good = bool(r.get("usable")) or "没有" in str(r.get("error", ""))
        print("[%s] 部位=%-4s 年龄=%-6s 性别=%-2s → 命中 %d %s"
              % ("PASS" if good else "FAIL", where or "-", band or "全部",
                 gender or "全部", len(r.get("matched") or []), r.get("error", "")))
        ok = ok and good

    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
