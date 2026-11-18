# -*- coding: utf-8 -*-
"""验证"切换语言后结果不消失"（这是用户报的 bug）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402


def main() -> int:
    ok = True

    # ---- 关键词检索 ----
    at = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=300)
    at.run()

    # 输入框顺序：① 部位自由填 ② 怎么不舒服 ③ 既往病史 ④ 想问什么 …
    kw = next((t for t in at.text_input if t.label == "想问什么"), None)
    if kw is None:
        print("[FAIL] 找不到搜索框")
        return 1
    kw.set_value("胃癌").run()

    btn = next((b for b in at.button if b.label == "查询"), None)
    if btn is None:
        print("[FAIL] 找不到查询按钮")
        return 1
    btn.click().run()
    saved = at.session_state.get("kw_result")
    print("[%s] 查询后结果已保存" % ("PASS" if saved else "FAIL"))
    ok = ok and bool(saved)

    # 切换语言 → 结果应该还在
    radio = next((r for r in at.radio if r.label == "结果语言"), None)
    if radio is not None:
        radio.set_value("中文").run()
        still = at.session_state.get("kw_result")
        print("[%s] 切换语言后结果仍在" % ("PASS" if still else "FAIL"))
        ok = ok and bool(still)

    # ---- 相似病例 ----
    at2 = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=300)
    at2.run()
    how = next((t for t in at2.text_input if t.label == "② 怎么不舒服"), None)
    if how is not None:
        how.set_value("咳嗽咳痰发热").run()
        go2 = next((b for b in at2.button if b.label == "找相似病例"), None)
        if go2 is not None:
            go2.click().run()
            sim = at2.session_state.get("sim_result")
            print("[%s] 相似病例结果已保存" % ("PASS" if sim else "FAIL"))
            ok = ok and bool(sim)
            radio2 = next((r for r in at2.radio if r.label == "结果语言"), None)
            if radio2 is not None:
                radio2.set_value("English").run()
                sim2 = at2.session_state.get("sim_result")
                print("[%s] 切换语言后相似结果仍在" % ("PASS" if sim2 else "FAIL"))
                ok = ok and bool(sim2)

    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
