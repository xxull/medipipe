# -*- coding: utf-8 -*-
"""
模块 5 验收：状态灯 + 报错翻译。

不花钱：不调主模型，只验证本地翻译和状态流转。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "plugins"))

from streamlit.testing.v1 import AppTest

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


ROOT = Path(__file__).parent
from core.loader_模块加载 import load as _load  # noqa: E402

errors = _load("core/errors_报错翻译.py", "core_errors_test")
engine = _load("core/engine_执行引擎.py", "core_engine_test2")
loader = _load("core/plugins_加载实例.py", "core_loader_test2")

# ---------------- 1. 报错翻译 ----------------
check("连不上 → 提示检查服务",
      "连不上" in errors.explain_local("requests.exceptions.ConnectionError: Max retries"),
      errors.explain_local("requests.exceptions.ConnectionError: Max retries"))
check("缺库 → 提示 pip 装",
      "pip" in errors.explain_local("ModuleNotFoundError: No module named 'xxx'"))
check("JSON 坏 → 提示强调只输出 JSON",
      "JSON" in errors.explain_local("json.decoder.JSONDecodeError: Expecting value"))
check("中文报错原样返回",
      "插件" in errors.explain_local("没找到这个插件（可能被移动或改名了）"))
check("怪错误也给建议",
      "建议" in errors.explain_local("something nobody has ever seen"))

# ---------------- 2. 状态灯事件 ----------------
inst = loader.load_instances({"text_compress": str(ROOT / "plugins" / "text_compress_文本压缩.py")})
events = []
engine.run_workflow(
    [{"step": "text_compress", "name": "压缩", "kind": "plugin", "brief": "", "order": 1, "parallel_group": ""}],
    inst, None, "这是一段用于测试的通用文本，包含标题、摘要和关键词。", on_event=events.append,
)
kinds = [e["event"] for e in events]
check("发出 start 事件", "start" in kinds, kinds)
check("发出 end 事件", "end" in kinds, kinds)
end_ev = next(e for e in events if e["event"] == "end")
check("end 事件带状态和耗时", end_ev.get("status") == "ok" and "ms" in end_ev, end_ev)

# 失败时事件里要有 error
bad = {"broken": type("X", (), {"execute_rich": lambda self, ctx: (_ for _ in ()).throw(RuntimeError("故意炸"))})()}
ev2 = []
engine.run_workflow(
    [{"step": "broken", "name": "坏", "kind": "plugin", "brief": "", "order": 1, "parallel_group": ""}],
    bad, None, "x", on_event=ev2.append,
)
end2 = next(e for e in ev2 if e["event"] == "end")
check("失败事件带 error", end2["status"] == "failed" and "故意炸" in end2["error"], end2)

# ---------------- 3. 界面：跑失败时显示红色解释 ----------------
at = AppTest.from_file("app.py", default_timeout=180)
at.run()
at.session_state["workflow"] = [
    {"step": "text_compress", "name": "压缩", "kind": "plugin", "tag": "插件（本地）",
     "file": str(ROOT / "plugins" / "text_compress_文本压缩.py"), "brief": "", "order": 1, "parallel_group": ""},
    {"step": "no_such_plugin", "name": "坏步骤", "kind": "plugin", "tag": "插件（本地）",
     "file": str(ROOT / "plugins" / "no_such.py"), "brief": "故意", "order": 2, "parallel_group": ""},
]
at.session_state["run_text"] = "这是一段用于测试的通用文本，包含标题、摘要和关键词。"
at.radio[0].set_value("选项 3 · 开始工作").run()
go = next((b for b in at.button if "开始工作" in b.label), None)
check("有开始按钮", go is not None)
if go:
    go.click().run()
    saved = at.session_state.get("run_report") or {}
    runs = saved.get("runs") or []
    rep = (runs[0]["report"] if runs else (saved.get("report") or {}))
    check("一步成功一步失败", [s["status"] for s in rep.get("steps", [])] == ["ok", "failed"],
          [s["status"] for s in rep.get("steps", [])])
    check("失败有中文解释", len(saved.get("explain") or []) == 1,
          str([e["local"][:30] for e in (saved.get("explain") or [])]))
    check("界面上有红色报错", len(at.error) >= 1, [str(e.value)[:40] for e in at.error])

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
