# -*- coding: utf-8 -*-
"""验证相似病例页（含药物表翻译）不报错。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402
from framework_b import b_相似  # noqa: E402


def main() -> int:
    r = b_相似.find_similar("胸部", "吸烟20年", "咳嗽咳痰发热", top_k=10)
    if not r.get("usable"):
        print("检索不可用：", r.get("error"))
        return 1

    at = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=300)
    at.session_state["sim_result"] = r
    # 语言选中文，触发药物表翻译分支
    at.run()
    radio = next((x for x in at.radio if x.label == "结果语言"), None)
    if radio is not None:
        radio.set_value("中文").run()
    ok = not at.exception
    print("[%s] 相似病例页（中文语言 + 药物表）%s"
          % ("PASS" if ok else "FAIL",
             "" if ok else str(at.exception[0].value)[:200]))
    print("  表格数:", len(at.dataframe))
    print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
