# -*- coding: utf-8 -*-
"""
模块 4 验收：执行引擎 + 选项 3 真跑。

用两段测试：
  1. 引擎层（不花钱）：串行 + 并行 + 插件真调用
  2. 界面层（不花钱）：选项 3 能拿到工作流、点开始能跑完
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


# ---------------- 1. 引擎层 ----------------
from core.loader_模块加载 import load as _load  # noqa: E402
engine = _load("core/engine_执行引擎.py", "core_engine_test")
loader = _load("core/plugins_加载实例.py", "core_loader_test")

ROOT = Path(__file__).parent
inst = loader.load_instances(
    {
        "text_compress": str(ROOT / "plugins" / "text_compress_文本压缩.py"),
        "ai_classifier": str(ROOT / "plugins" / "ai_classifier_文本分类.py"),
        "ai_extractor": str(ROOT / "plugins" / "ai_extractor_字段抽取.py"),
    }
)
check("插件实例加载", len(inst) == 3, list(inst))

TEXT = "标题：本地数据流水线示例\n摘要：这是一个通用文本处理示例，演示压缩、分类、字段抽取和入库。\n关键词：流水线，插件，数据，示例\n正文：框架把长文本先压缩，再分类，并抽取标题、摘要和关键词。"

wf_serial = [
    {"step": "text_compress", "name": "压缩", "kind": "plugin", "brief": "压到 800 字", "order": 1, "parallel_group": ""},
    {"step": "ai_extractor", "name": "抽取", "kind": "plugin", "brief": "抽三个字段", "order": 2, "parallel_group": ""},
]
r1 = engine.run_workflow(wf_serial, inst, None, TEXT)
check("串行两步都成功", r1["ok"] and len(r1["steps"]) == 2, [s["status"] for s in r1["steps"]])
check("抽取拿到了摘要", "通用" in str(r1["steps"][1]["output"].get("summary", "")),
      r1["steps"][1]["output"])

wf_par = [
    {"step": "text_compress", "name": "压缩", "kind": "plugin", "brief": "", "order": 1, "parallel_group": ""},
    {"step": "ai_classifier", "name": "分类", "kind": "plugin", "brief": "", "order": 2, "parallel_group": "g1"},
    {"step": "ai_extractor", "name": "抽取", "kind": "plugin", "brief": "", "order": 3, "parallel_group": "g1"},
]
r2 = engine.run_workflow(wf_par, inst, None, TEXT)
check("并行组一起跑", r2["ok"] and len(r2["steps"]) == 3, [s["status"] for s in r2["steps"]])

# 失败要能被抓住
bad = {"broken": type("X", (), {"execute_rich": lambda self, ctx: (_ for _ in ()).throw(RuntimeError("故意出错"))})()}
r3 = engine.run_workflow(
    [{"step": "broken", "name": "坏插件", "kind": "plugin", "brief": "", "order": 1, "parallel_group": ""}],
    bad, None, "x",
)
check("插件报错不会崩引擎", r3["ok"] is False and "故意出错" in r3["steps"][0]["error"], r3["steps"][0]["error"])

# ---------------- 2. 界面层 ----------------
at = AppTest.from_file("app.py", default_timeout=180)
at.run()
at.radio[0].set_value("选项 3 · 开始工作").run()
check("空画布时给提示", any("画布还是空的" in str(i.value) for i in at.info))

# 塞一个工作流进去（等价于画布画好了）
at.session_state["workflow"] = [
    {"step": "text_compress", "name": "压缩", "kind": "plugin", "tag": "插件（本地）",
     "file": str(ROOT / "plugins" / "text_compress_文本压缩.py"), "brief": "压一压", "order": 1, "parallel_group": ""},
    {"step": "ai_extractor", "name": "抽取", "kind": "plugin", "tag": "插件（模型）",
     "file": str(ROOT / "plugins" / "ai_extractor_字段抽取.py"), "brief": "抽字段", "order": 2, "parallel_group": ""},
]
at.session_state["run_text"] = TEXT
at.run()

go = next((b for b in at.button if "开始工作" in b.label), None)
check("有开始工作按钮", go is not None)
if go:
    go.click().run()
    saved = at.session_state.get("run_report") or {}
    # 页面现在统一用 runs 列表（单条也有 1 个），兼容两种结构
    runs = saved.get("runs") or []
    rep = (runs[0]["report"] if runs else (saved.get("report") or {}))
    check("界面跑完了", rep.get("ok") is True, [s["status"] for s in rep.get("steps", [])])
    check("拿到最终文本", bool(rep.get("text")), str(rep.get("text"))[:40])
    check("显示了花费", any(m.label == "主模型花费" for m in at.metric))

# ---------------- 3. 输入合并（一个框，自动识别网址/文本） ----------------
at2 = AppTest.from_file("app.py", default_timeout=120)
at2.run()
at2.radio[0].set_value("选项 3 · 开始工作").run()
boxes = [t for t in at2.text_area if "粘贴文本" in t.label]
check("只有一个输入框（已合并）", len(boxes) == 1, [t.label for t in at2.text_area])
if boxes:
    boxes[0].set_value("https://example.com/a").run()
    check("网址被识别", any("识别为网址" in str(c.value) for c in at2.caption),
          [str(c.value) for c in at2.caption][:3])
    boxes[0].set_value("标题：示例文本").run()
    check("文本被识别", any("识别为文本" in str(c.value) for c in at2.caption),
          [str(c.value) for c in at2.caption][:3])
check("框架页面不出现具体数据源", not any("搜一下" in b.label for b in at2.button),
      "数据来源应该是插件，不该写死在页面里")

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
