# -*- coding: utf-8 -*-
"""模块 1 验收：三个选项页都能渲染，主模型配置能存进 session_state。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from streamlit.testing.v1 import AppTest

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


at = AppTest.from_file("app.py", default_timeout=120)
at.run()

check("首屏无异常", not at.exception, str(at.exception[0].value) if at.exception else "")
check("有选项切换条", len(at.radio) >= 1)
labels = at.radio[0].options
check("三个选项都在", len(labels) == 3, labels)
check("默认选项 1", "选项 1" in at.radio[0].value, at.radio[0].value)

# ---- 选项 1：主模型配置 ----
check("有厂商下拉", len(at.selectbox) >= 1, [s.label for s in at.selectbox])
providers = at.selectbox[0].options
check("四家厂商", len(providers) == 4, providers)
check("有 Key 输入框", any(t.label == "API Key" for t in at.text_input))
check("有保存按钮", any("确认这个 Key" in b.label for b in at.button))

# 填 Key 后应该显示"已就绪"
key_input = next((t for t in at.text_input if t.label == "API Key"), None)
if key_input:
    key_input.set_value("sk-test-123456").run()
    save = next((b for b in at.button if "确认这个 Key" in b.label), None)
    if save:
        save.click().run()
    check("Key 存进了 session_state", at.session_state.get("main_api_key") == "sk-test-123456")
    check("显示已就绪", any("主模型已就绪" in str(s.value) for s in at.success),
          [str(s.value)[:20] for s in at.success])

# ---- 选项 2：画布 ----
at.radio[0].set_value("选项 2 · 画布编排").run()
check("选项 2 无异常", not at.exception, str(at.exception[0].value) if at.exception else "")
check("有扫描按钮", any("重新扫描插件" in b.label for b in at.button))
check("有添加节点按钮", any("添加这个节点" in b.label for b in at.button))
check("有全电脑扫描", any("全电脑扫描" in b.label for b in at.button))

# ---- 选项 3：开始工作 ----
at.radio[0].set_value("选项 3 · 开始工作").run()
check("选项 3 无异常", not at.exception, str(at.exception[0].value) if at.exception else "")
check("有输入区", any("粘贴文本" in t.label for t in at.text_area), [t.label for t in at.text_area])
check("空画布有提示", any("画布还是空的" in str(i.value) for i in at.info))

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
