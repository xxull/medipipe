# -*- coding: utf-8 -*-
"""B 端界面全流程（AppTest 真点）：概览 / 相似病例 / 关键词 / 总结 / 自检。

用法：
    python tools\测_B界面.py            # 测当前仓库
    python tools\测_B界面.py <仓库目录>  # 测别的副本

需要库里已经有数据（先跑 导入样例数据.py / 导入开放数据.py）。
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
                print("[PASS] %-38s %5.1fs" % (name, time.time() - t0))
                return r
            except AssertionError as exc:
                OK = False
                print("[FAIL] %-38s %s" % (name, exc))
            except Exception as exc:  # noqa: BLE001
                OK = False
                print("[FAIL] %-38s %s: %s" % (name, type(exc).__name__, str(exc)[:120]))
                traceback.print_exc(limit=2)
        return wrapper
    return deco


def no_exc(at, where=""):
    if at.exception:
        raise AssertionError("%s 有异常: %s" % (where, [str(e.value)[:120] for e in at.exception]))


def btn(at, text):
    for b in at.button:
        if text in str(getattr(b, "label", "")):
            return b
    return None


def click(at, text):
    b = btn(at, text)
    assert b is not None, "找不到按钮：%s（现有：%s）" % (
        text, [str(getattr(x, "label", ""))[:12] for x in at.button])
    b.click()
    at.run()
    no_exc(at, "点击「%s」后" % text)


def radio(at, label_kw, value, index=0):
    hits = [r for r in at.radio if label_kw in str(getattr(r, "label", ""))]
    if not hits:
        raise AssertionError("找不到 radio：%s" % label_kw)
    hits[min(index, len(hits) - 1)].set_value(value)
    at.run()
    no_exc(at, "设置 radio %s=%s" % (label_kw, value))


def fill_inputs(at, values):
    boxes = list(at.text_input)
    assert len(boxes) >= len(values), "文本输入框只有 %d 个" % len(boxes)
    for box, v in zip(boxes, values):
        box.set_value(v)
    at.run()
    no_exc(at, "填输入框")


at = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=600)
at.run()
no_exc(at, "首屏")
print("标签页数：%d" % len(at.tabs))


@step("概览：指标/表格渲染")
def t_overview():
    assert len(at.metric) >= 1 or len(at.dataframe) >= 1, "概览没有指标也没有表格"


t_overview()


@step("相似病例：填写并检索")
def t_search_similar():
    # 默认在“相似病例”页签，其输入框是前三个
    fill_inputs(at, ["胸部", "咳嗽咳痰、发热三天", "吸烟20年"])
    for sb in at.selectbox:
        label = str(getattr(sb, "label", ""))
        if "年龄段" in label:
            sb.set_value("18-44")
        elif "性别" in label:
            sb.set_value("男")
    at.run()
    click(at, "找相似病例")
    assert at.tabs, "结果子标签页没出来"


t_search_similar()


@step("相似病例：①类似疾病表")
def t_tab1():
    dfs = [d for d in at.dataframe if "疾病" in str(getattr(d.value, "columns", []))]
    assert dfs, "没找到疾病表"


t_tab1()


@step("相似病例：翻译成中文")
def t_translate_zh():
    radio(at, "结果语言", "中文")
    click(at, "翻译成")
    # 翻译后应该有「恢复原文」按钮
    assert btn(at, "恢复原文") is not None, "翻译后没有「恢复原文」按钮"


t_translate_zh()


@step("相似病例：科室分布代表疾病也是中文")
def t_dept_zh():
    found = None
    for d in at.dataframe:
        cols = [str(c) for c in getattr(d.value, "columns", [])]
        if "代表疾病" in cols:
            found = d.value["代表疾病"].head(3).tolist()
            break
    assert found is not None, "没找到科室分布表"
    text = "".join(str(x) for x in found)
    assert any("\u4e00" <= ch <= "\u9fff" for ch in text), "代表疾病还是英文：%s" % found


t_dept_zh()


@step("相似病例：恢复原文")
def t_restore():
    click(at, "恢复原文")
    assert btn(at, "翻译成") is not None, "恢复原文后按钮没回来"


t_restore()


@step("相似病例：翻译成 English")
def t_translate_en():
    radio(at, "结果语言", "English")
    click(at, "翻译成")
    assert btn(at, "恢复原文") is not None, "English 翻译后没有恢复按钮"
    click(at, "恢复原文")


t_translate_en()


@step("相似病例：查看病例（展开）")
def t_detail():
    assert at.expander, "⑤ 查看病例里没有可展开项"


t_detail()


@step("关键词检索：查询 + 结果")
def t_kw():
    radio(at, "结果语言", "原文", index=1)
    kw = [b for b in at.text_input if "想问什么" in str(getattr(b, "label", ""))]
    assert kw, "找不到关键词输入框，现有：%s" % [str(getattr(b, "label", "")) for b in at.text_input]
    kw[0].set_value("咳嗽")
    at.run()
    click(at, "查询")
    caps = " ".join(str(c.value) for c in at.caption)
    assert "命中" in caps, "查询后没有结果提示：%s" % caps[-100:]


t_kw()


@step("关键词检索：切换结果语言不丢结果")
def t_kw_lang():
    radio(at, "结果语言", "中文", index=1)
    txt = " ".join(str(c.value) for c in at.caption)
    assert "命中" in txt, "切换语言后结果消失了：%s" % txt[:80]


t_kw_lang()


@step("病历总结：无 Key 时提示")
def t_summary_warn():
    warns = " ".join(str(w.value) for w in at.warning)
    assert "Key" in warns, "病历总结页没有 Key 提示：%s" % warns[:100]


t_summary_warn()


@step("自检：三盏灯 + Key 区")
def t_health():
    labels = " ".join(str(m.value) for m in at.markdown)
    assert "主模型 Key" in labels, "自检页没有 Key 区"
    assert len(at.text_input) >= 1, "自检页没有 Key 输入框"


t_health()


print("\n结果：", "全部通过 ✅" if OK else "有失败 ❌")
sys.exit(0 if OK else 1)
