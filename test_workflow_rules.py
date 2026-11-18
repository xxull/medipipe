# -*- coding: utf-8 -*-
"""回归测试：step 唯一、并行不破坏依赖、有环阻断执行。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from streamlit.testing.v1 import AppTest  # noqa: E402

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


at = AppTest.from_file("app.py", default_timeout=120)
at.run()
at.radio[0].set_value("选项 2 · 画布编排").run()

nodes = [
    {"id": "n1", "label": "A", "choice": "文本压缩", "name_mode": "用原名", "brief": "", "pos": (80, 40)},
    {"id": "n2", "label": "B", "choice": "文本压缩", "name_mode": "用原名", "brief": "", "pos": (300, 40)},
    {"id": "n3", "label": "C", "choice": "文本压缩", "name_mode": "用原名", "brief": "", "pos": (300, 160)},
]
edges = [
    {"id": "e1", "source": "n1", "target": "n2", "note": ""},
    {"id": "e2", "source": "n1", "target": "n3", "note": ""},
    {"id": "e3", "source": "n2", "target": "n3", "note": ""},
]
at.session_state["flow_nodes"] = nodes
at.session_state["flow_edges"] = edges
at.session_state["flow_state"] = None
at.session_state["graph_ver"] = 99
at.session_state["built_ver"] = -1
at.run()

wf = at.session_state.get("workflow") or []
check("step 使用唯一节点 id", len({w["step"] for w in wf}) == 3, [w["step"] for w in wf])
check("两个同类型插件仍有独立 key", all(w.get("key") == "text_compress" for w in wf))
check("有依赖的 C 不被并行", all(not w.get("parallel_group") for w in wf),
      [(w["name"], w.get("parallel_group")) for w in wf])

at.session_state["flow_edges"] = edges + [{"id": "e4", "source": "n3", "target": "n1", "note": ""}]
at.session_state["flow_state"] = None
at.session_state["graph_ver"] = 100
at.session_state["built_ver"] = -1
at.run()
check("有环时 workflow 为空", not (at.session_state.get("workflow") or []))
check("有环时有中文错误", any("有环" in str(e.value) for e in at.error))

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
