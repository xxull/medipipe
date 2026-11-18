# -*- coding: utf-8 -*-
"""A 端界面全流程（AppTest 真点）：三页导航 / 配置页 / 画布 / 单条跑 / 批量跑。

用法：
    python tools\测_A界面.py            # 测当前仓库
    python tools\测_A界面.py <仓库目录>  # 测别的副本
"""
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent).resolve()
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

OK = True


def step(name):
    def deco(fn):
        def wrapper(*a, **kw):
            global OK
            t0 = time.time()
            try:
                r = fn(*a, **kw)
                print("[PASS] %-34s %5.1fs" % (name, time.time() - t0))
                return r
            except AssertionError as exc:
                OK = False
                print("[FAIL] %-34s %s" % (name, exc))
            except Exception as exc:  # noqa: BLE001
                OK = False
                print("[FAIL] %-34s %s: %s" % (name, type(exc).__name__, str(exc)[:140]))
                traceback.print_exc(limit=2)
        return wrapper
    return deco


def no_exc(at, where=""):
    if at.exception:
        raise AssertionError("%s 有异常: %s" % (where, [str(e.value)[:140] for e in at.exception]))


def goto(at, label):
    nav = [r for r in at.radio if "选择功能" in str(getattr(r, "label", ""))][0]
    nav.set_value(label)
    at.run()
    no_exc(at, "切到「%s」" % label)


def click(at, text):
    b = None
    for x in at.button:
        if text in str(getattr(x, "label", "")):
            b = x
            break
    assert b is not None, "找不到按钮 %s，现有：%s" % (
        text, [str(getattr(x, "label", ""))[:14] for x in at.button])
    assert not b.disabled, "按钮「%s」是禁用状态" % text
    b.click()
    at.run()
    no_exc(at, "点击「%s」" % text)


at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=600)
at.run()
no_exc(at, "首屏")


@step("首屏渲染 + 三页导航")
def t_shell():
    nav = [r for r in at.radio if "选择功能" in str(getattr(r, "label", ""))]
    assert nav, "没有三页导航"
    print("      页面：", nav[0].options)
    assert len(nav[0].options) == 3, "导航不是三页"


t_shell()


@step("第1页：主模型配置可交互")
def t_page1():
    goto(at, "选项 1 · 主模型配置")
    assert at.text_input or at.selectbox, "第1页没有任何输入控件"
    # 「测试连接」在没 Key 时应该给错误提示，而不是崩
    if any("测试" in str(getattr(b, "label", "")) for b in at.button):
        click(at, "测试")
        assert at.error or at.warning or at.success, "测试连接没有任何反馈"


t_page1()


@step("第2页：画布加节点 + 生成 workflow")
def t_page2_add():
    goto(at, "选项 2 · 画布编排")
    boxes = [s for s in at.selectbox if "新节点" in str(getattr(s, "label", ""))]
    assert boxes, "找不到「新节点用什么」下拉"
    opts = list(boxes[0].options)
    raw = next((o.split("（")[0] for o in opts if "文本压缩" in str(o)), None)
    assert raw, "下拉里没有文本压缩"
    at.session_state["add_choice"] = raw
    at.run()
    click(at, "添加这个节点")
    nodes = at.session_state.get("flow_nodes") or []
    assert len(nodes) == 1, "节点数不对：%d" % len(nodes)
    wf = at.session_state.get("workflow") or []
    assert wf and wf[0]["key"] == "text_compress", "workflow 不对：%s" % wf


t_page2_add()


@step("第2页：撤销 + 重加")
def t_page2_undo():
    click(at, "撤销")
    assert not (at.session_state.get("flow_nodes") or []), "撤销后节点没消失"
    at.session_state["add_choice"] = "文本压缩"
    at.run()
    click(at, "添加这个节点")
    assert len(at.session_state.get("flow_nodes") or []) == 1, "重加失败"


t_page2_undo()


def _fill(at, key, text):
    arr = [t for t in at.text_area if t.key == key]
    assert arr, "找不到输入框 %s（现有 %s）" % (key, [t.key for t in at.text_area])
    arr[0].set_value(text)
    at.run()
    no_exc(at, "填 %s" % key)


def _report(at):
    r = at.session_state.get("run_report") or {}
    runs = r.get("runs") or []
    assert runs, "没有跑出结果"
    return runs


@step("第3页：单条跑通")
def t_page3_single():
    goto(at, "选项 3 · 开始工作")
    _fill(at, "run_text", "这是一段用于测试的文本，需要足够长，好让压缩插件有东西可处理。" * 4)
    click(at, "开始工作")
    runs = _report(at)
    rep = runs[-1]["report"]
    assert rep["ok"], "执行失败：%s" % rep
    steps = rep["steps"]
    assert steps and steps[0]["status"] == "ok", "步骤状态不对：%s" % steps
    print("      步骤 %s 用时 %s ms" % (steps[0]["step"], steps[0]["ms"]))


t_page3_single()


@step("第3页：批量跑（3 条）+ 表格")
def t_page3_batch():
    radio = [r for r in at.radio if "跑几条" in str(getattr(r, "label", ""))][0]
    radio.set_value("批量（一行一条）")
    at.run()
    _fill(at, "run_bulk", "第一条：咳嗽咳痰三天。\n第二条：发热伴乏力。\n第三条：头痛、眩晕。")
    click(at, "开始工作")
    runs = _report(at)
    assert len(runs) == 3, "批量跑了 %d 条" % len(runs)
    assert all(r["report"]["ok"] for r in runs), "有批次失败"
    assert at.dataframe, "批量结果没有表格"
    assert any("下载" in str(getattr(b, "label", "")) for b in at.get("download_button")), "没有下载 CSV 按钮"


t_page3_batch()


print("\n结果：", "全部通过 ✅" if OK else "有失败 ❌")
sys.exit(0 if OK else 1)
