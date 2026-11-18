# -*- coding: utf-8 -*-
"""模块 2 + 扫描器验收：本机扫描、自动命名、三种命名方式、点选连线、并行、环检测。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from streamlit.testing.v1 import AppTest

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + detail if detail else ""))
    if not cond:
        ok = False


def box(at, label):
    return next((s for s in at.selectbox if s.label == label), None)


def btn(at, text):
    return next((b for b in at.button if text in b.label), None)


at = AppTest.from_file("app.py", default_timeout=120)
at.run()
at.radio[0].set_value("选项 2 · 画布编排").run()
check("画布页无异常", not at.exception, str(at.exception[0].value) if at.exception else "")

# ---------- 1. 扫描本机插件 ----------
add_box = box(at, "新节点用什么")
opts = add_box.options if add_box else []
check("扫到了插件（至少 4 个）", len(opts) >= 4, "共 %d 个：%s" % (len(opts), opts[:6]))
check("扫到网页抓取", any("网页抓取" in o for o in opts), str(opts))

# ---------- 2. 加三个节点 ----------
def add_node(name="网页抓取"):
    box(at, "新节点用什么").set_value(name).run()
    btn(at, "添加这个节点").click().run()

add_node("网页抓取")
add_node("文本压缩")
add_node("文本分类")
nodes = at.session_state["flow_nodes"]
check("三个节点都在", len(nodes) == 3, str([(n["id"], n["choice"]) for n in nodes]))
check("新节点名字空着", all(n["label"] == "" for n in nodes))

# ---------- 3. 改类型 → 自动命名 ----------
sel = box(at, "选节点")
sel.set_value(sel.options[1]).run()
check("选中的是 n1", at.session_state["edit_node"] == "n1", at.session_state["edit_node"])

box(at, "类型（从本机扫描）").set_value("文本压缩").run()
nodes = at.session_state["flow_nodes"]
check("改类型后自动命名", nodes[0]["label"].endswith("1") and len(nodes[0]["label"]) <= 4,
      nodes[0]["label"])

# ---------- 4. 命名方式：用原名 ----------
box(at, "怎么起名").set_value("用原名").run()
nodes = at.session_state["flow_nodes"]
check("用原名 = 插件自己的名字", nodes[0]["label"] == "文本压缩", nodes[0]["label"])

# ---------- 5. 命名方式：我自己起 ----------
box(at, "怎么起名").set_value("我自己起").run()
name_box = next((t for t in at.text_input if t.label == "名字"), None)
check("出现手填名字框", name_box is not None)
if name_box:
    name_box.set_value("压一下").run()
    check("手填名字生效", at.session_state["flow_nodes"][0]["label"] == "压一下")

# ---------- 6. 命名方式：主模型起（没 Key 时给中文提示） ----------
box(at, "怎么起名").set_value("主模型起名").run()
mbtn = btn(at, "让主模型起名")
check("有主模型起名按钮", mbtn is not None)
if mbtn:
    mbtn.click().run()
    msgs = [str(w.value) for w in at.warning] + [str(i.value) for i in at.info]
    check("没 Key 时提示去配 Key", any("主模型 Key" in m for m in msgs), str(msgs)[:80])

# 把第一个节点改回网页抓取（后面要验证"联网"标签）
box(at, "类型（从本机扫描）").set_value("网页抓取").run()
# ---------- 7. 点选连线 ----------
box(at, "从").set_value(box(at, "从").options[0]).run()
box(at, "到").set_value(box(at, "到").options[1]).run()
btn(at, "连上").click().run()
check("连上第一条线", len(at.session_state["flow_edges"]) == 1)

box(at, "从").set_value(box(at, "从").options[0]).run()
box(at, "到").set_value(box(at, "到").options[2]).run()
btn(at, "连上").click().run()
check("连上第二条线", len(at.session_state["flow_edges"]) == 2)

wf = at.session_state["workflow"]
parallel = [w for w in wf if w["parallel_group"]]
check("识别出并行", len(parallel) == 2, str([(w["name"], w["parallel_group"]) for w in wf]))

# ---------- 8. 类型标签带联网/模型信息 ----------
tags = {w["name"]: w["tag"] for w in wf}
check("抓取被标成联网", any("联网" in t for t in tags.values()), str(tags))
check("JSON 带 needs 字段", all("needs" in w for w in wf))

# ---------- 9. 环检测 ----------
box(at, "从").set_value(box(at, "从").options[1]).run()
box(at, "到").set_value(box(at, "到").options[0]).run()
btn(at, "连上").click().run()
check("有环报中文错", any("有环" in str(e.value) for e in at.error), str([e.value for e in at.error])[:60])

# ---------- 10. 全电脑扫描 ----------
scan_btn = btn(at, "全电脑扫描")
check("有全电脑扫描按钮", scan_btn is not None)
if scan_btn:
    scan_btn.click().run()
    stats = at.session_state.get("disk_stats") or {}
    check("全盘扫到了插件", len(stats.get("found", [])) > 0,
          "找到 %d 个，检查 %d 文件，%s 秒" % (len(stats.get("found", [])), stats.get("checked", 0), stats.get("seconds")))
    md = " ".join(str(m.value) for m in at.markdown)
    check("有'扫不全'的免责说明", "扫不全" in md, md[:60] if md else "没找到说明文字")

# ---------- 11. 从电脑里选择（不点弹窗，只验证按钮在） ----------
check("有选择文件夹按钮", btn(at, "从我的电脑里选择") is not None)

# ---------- 12. 轻量模型要能扫到（不依赖 Ollama 服务） ----------
opts_now = box(at, "新节点用什么").options
model_opts = [o for o in opts_now if "轻量模型" in o]
check("清单里有轻量模型", len(model_opts) > 0, str(model_opts[:4]))
check("扫到了 Ollama 的 bge-m3 或 qwen3-vl",
      any("bge-m3" in o or "qwen3-vl" in o for o in opts_now), str(model_opts[:6]))

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
