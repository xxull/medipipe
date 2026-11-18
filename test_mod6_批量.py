# -*- coding: utf-8 -*-
"""模块 6 验收：批量跑（一行一条 → 表格 + CSV）与画布按钮修复。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from streamlit.testing.v1 import AppTest

ok = True
ROOT = Path(__file__).parent


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


WF = [
    {"step": "text_compress", "name": "压缩", "kind": "plugin", "tag": "插件（本地）",
     "file": str(ROOT / "plugins" / "text_compress_文本压缩.py"), "brief": "", "order": 1, "parallel_group": ""},
    {"step": "ai_extractor", "name": "抽取", "kind": "plugin", "tag": "插件（模型）",
     "file": str(ROOT / "plugins" / "ai_extractor_字段抽取.py"), "brief": "", "order": 2, "parallel_group": ""},
]

at = AppTest.from_file("app.py", default_timeout=180)
at.run()
at.session_state["workflow"] = WF
at.radio[0].set_value("选项 3 · 开始工作").run()

check("有单条/批量切换", any(r.label == "跑几条" for r in at.radio))
bulk_radio = next(r for r in at.radio if r.label == "跑几条")
bulk_radio.set_value("批量（一行一条）").run()

box = next((t for t in at.text_area if "一行一条" in t.label), None)
check("批量有输入框", box is not None)

if box:
    box.set_value(
        "标题：示例一；摘要：这是第一条通用文本，用于测试批量流水线；关键词：示例，批量，测试\n"
        "标题：示例二；摘要：这是第二条通用文本，用于测试字段抽取；关键词：流水线，插件，数据\n"
        "标题：示例三；摘要：这是第三条通用文本，用于测试 CSV 导出；关键词：压缩，分类，入库"
    ).run()
    caption = [str(c.value) for c in at.caption if "识别到" in str(c.value)]
    check("识别出 3 条", any("3" in c for c in caption), caption)

    go = next((b for b in at.button if "开始工作" in b.label), None)
    go.click().run()

    saved = at.session_state.get("run_report") or {}
    runs = saved.get("runs") or []
    check("跑了 3 条", len(runs) == 3, len(runs))
    check("三条都成功", all(r["report"]["ok"] for r in runs),
          [r["report"]["ok"] for r in runs])
    check("标记为批量", saved.get("batch") is True)

    df = at.dataframe[0].value if at.dataframe else None
    check("出表格且 3 行", df is not None and len(df) == 3, None if df is None else len(df))
    if df is not None:
        cols = list(df.columns)
        check("表格有状态列", "状态" in cols, cols)
        check("表格有插件返回的字段（列是动态的）", any(c in cols for c in
        ("title", "summary", "keywords", "category")), cols)

    dl = at.get("download_button")
    check("能下载 CSV", any("CSV" in d.label for d in dl), [d.label for d in dl])

    # 单条模式仍然正常
    bulk_radio = next(r for r in at.radio if r.label == "跑几条")
    bulk_radio.set_value("单条").run()
    single_box = next((t for t in at.text_area if "粘贴文本" in t.label), None)
    check("单条输入框还在", single_box is not None)

# 画布：自带工具条已关掉，换成"适应窗口"
at2 = AppTest.from_file("app.py", default_timeout=120)
at2.run()
at2.radio[0].set_value("选项 2 · 画布编排").run()
check("画布有适应窗口按钮", any("适应窗口" in b.label for b in at2.button),
      [b.label for b in at2.button][:8])

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
