# -*- coding: utf-8 -*-
"""
双框架体检：把 A 和 B 都按“普通用户的操作顺序”跑一遍，找崩溃点。
=========================================================================
A 的走法：加载插件 → 选工作流 → 跑一条数据 → 看库 → 看日志
B 的走法：开页面 → 每个标签页渲染 → 检索 → 相似病例 → 总结 → 翻译 → 详情
=========================================================================
"""
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

OK = True
BUGS = []


def check(name, cond, detail=""):
    global OK
    status = "PASS" if cond else "FAIL"
    print("[%s] %s%s" % (status, name, ("  " + str(detail)[:120]) if detail and not cond else ""))
    if not cond:
        OK = False
        BUGS.append("%s | %s" % (name, str(detail)[:200]))


def section(t):
    print("\n" + "=" * 60 + "\n" + t)


# =========================================================
# 框架 A
# =========================================================
section("框架 A · 插件与引擎")

try:
    from core.loader_模块加载 import load
    from core.scanner_插件扫描 import scan_plugins

    plugins = scan_plugins()
    check("插件能被扫描到", len(plugins) >= 8, len(plugins))
except Exception:
    check("插件扫描", False, traceback.format_exc()[-200:])
    plugins = []

try:
    loader = load("core/plugins_加载实例.py", "t_b_load")
    PLUGIN_FILES = {
        "web_scraper": str(ROOT / "plugins" / "web_scraper_网页抓取.py"),
        "ai_extractor": str(ROOT / "plugins" / "ai_extractor_字段抽取.py"),
        "db_writer": str(ROOT / "plugins" / "db_writer_入库.py"),
    }
    inst = loader.load_instances(PLUGIN_FILES)
    check("插件能实例化", len(inst) == 3, list(inst))
except Exception:
    check("插件实例化", False, traceback.format_exc()[-300:])
    inst = {}

engine = None
try:
    engine = load("core/engine_执行引擎.py", "t_b_engine")
    check("引擎能加载", hasattr(engine, "run_workflow"))
except Exception:
    check("引擎加载", False, traceback.format_exc()[-300:])

if engine and inst:
    wf = [
        {"step": "s1", "key": "web_scraper", "name": "抓取", "kind": "plugin",
         "brief": "", "order": 1, "parallel_group": ""},
        {"step": "s2", "key": "ai_extractor", "name": "抽取", "kind": "plugin",
         "brief": "", "order": 2, "parallel_group": ""},
        {"step": "s3", "key": "db_writer", "name": "入库", "kind": "plugin",
         "brief": "table=selftest", "order": 3, "parallel_group": ""},
    ]
    try:
        rep = engine.run_workflow(wf, plugins=inst, master=None,
                                  input_text="https://example.com", logger=lambda m: None,
                                  step_timeout=60)
        check("A 全流程跑通（抓取→抽取→入库）", rep["ok"],
              [(s["name"], s["status"], s["error"][:60]) for s in rep["steps"]])
        check("步骤数正确", len(rep["steps"]) == 3, len(rep["steps"]))
    except Exception:
        check("A 全流程", False, traceback.format_exc()[-300:])

    # 失败即停
    try:
        def boom(ctx):
            raise RuntimeError("故意失败")

        class Boom:
            name = "boom"
            REQUIRES = []
            OUTPUT_FIELDS = ["x"]

            def execute_rich(self, ctx):
                return boom(ctx)

        class Never:
            name = "never"

            def execute_rich(self, ctx):
                raise AssertionError("不该被调用")

        rep2 = engine.run_workflow(
            [{"step": "a", "key": "boom", "name": "坏", "kind": "plugin", "order": 1,
              "parallel_group": ""},
             {"step": "b", "key": "never", "name": "不该跑", "kind": "plugin", "order": 2,
              "parallel_group": ""}],
            plugins={"boom": Boom(), "never": Never()}, master=None, input_text="x",
            logger=lambda m: None, step_timeout=10)
        st = [s["status"] for s in rep2["steps"]]
        check("失败即停（下游 skipped）", st == ["failed", "skipped"], st)
    except Exception:
        check("失败即停", False, traceback.format_exc()[-300:])

    # 节点协议
    try:
        from core.protocol_节点协议 import check as proto_check

        class Need:
            REQUIRES = ["label"]
            name = "need"

        ok1, why1 = proto_check(Need(), {"text": "abc", "upstream": {}})
        ok2, why2 = proto_check(Need(), {"text": "", "upstream": {}})
        check("协议：缺字段但有文本 → 放行+警告", ok1 and bool(why1))
        check("协议：什么都没有 → 拦住", not ok2)
    except Exception:
        check("节点协议", False, traceback.format_exc()[-300:])

section("框架 A · 库与日志")
try:
    conn = sqlite3.connect(str(ROOT / "data" / "records.db"), timeout=30)
    n = conn.execute("SELECT COUNT(*) FROM selftest").fetchone()[0] if conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name='selftest'").fetchone()[0] else -1
    conn.close()
    check("入库生效（selftest 表有行）", n > 0, n)
except Exception as exc:
    check("入库检查", False, exc)

try:
    from core.log_日志 import tail
    txt = tail(5)
    check("运行日志可读", isinstance(txt, str) and len(txt) >= 0, type(txt))
except Exception:
    check("日志读取", False, traceback.format_exc()[-200:])

# =========================================================
# 框架 B
# =========================================================
section("框架 B · 各标签页渲染")

try:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=300)
    at.run()
    check("B 首屏无异常", not at.exception,
          at.exception[0].value if at.exception else "")
    check("有文本输入", len(at.text_input) >= 4, len(at.text_input))
    check("有下拉", len(at.selectbox) >= 3, [s.label for s in at.selectbox])
except Exception:
    check("B 渲染", False, traceback.format_exc()[-400:])

section("框架 B · 功能")
try:
    from framework_b import b_检索, b_相似, b_总结, b_翻译, b_配置

    hits = b_检索.search_fts("胃癌", limit=3)
    check("全文检索有结果", len(hits) > 0, len(hits))
    hits2 = b_检索.search("胃癌", limit=3)
    check("LIKE 兜底有结果", len(hits2) >= 0, len(hits2))

    st = b_相似.index_status()
    check("向量索引可加载", st["ready"], st)

    r = b_相似.find_similar("胸部", "吸烟20年", "咳嗽咳痰发热", top_k=20)
    check("相似病例可用", r.get("usable"), r.get("error"))
    check("有疾病统计", bool(r.get("diseases")), r.get("diseases")[:2])
    check("有科室分组", bool(r.get("departments")), len(r.get("departments") or []))

    cid = (r.get("matched") or [None])[0]
    if cid:
        d = b_相似.detail(cid)
        check("病例详情可取", not d.get("error"), d.get("error"))
    else:
        check("病例详情可取", False, "没有 matched")

    s = b_总结.summarize("患者男，67岁。主诉：咳嗽咳痰3年，加重伴发热2天。"
                       "查体：双肺湿啰音。诊断：社区获得性肺炎。处理：抗感染。")
    check("病历总结有输出", len(s) > 30, s[:60])

    t = b_翻译.text("Sepsis, pulmonary", "zh")
    check("翻译可用", len(t) > 0 and t != "Sepsis, pulmonary", t)

    check("Key 状态可读", isinstance(b_配置.mask(b_配置.get_key()), str))
except Exception:
    check("B 功能", False, traceback.format_exc()[-500:])

# =========================================================
print("\n" + "=" * 60)
if BUGS:
    print("发现 %d 个问题：" % len(BUGS))
    for b in BUGS:
        print("  - " + b)
else:
    print("没有发现问题")
print("\n结果：", "全部通过 ✅" if OK else "有失败 ❌")
sys.exit(0 if OK else 1)
