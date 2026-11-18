# -*- coding: utf-8 -*-
"""模块 7 验收：入库插件（建表 / 去重 / 加列 / 引擎传 upstream）。"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "plugins"))

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


from core.loader_模块加载 import load as _load  # noqa: E402

# 插件文件名改成「英文_中文.py」了，按路径加载
_db_mod = _load("plugins/db_writer_入库.py", "test_db_writer_mod")
DBWriter = _db_mod.DBWriter

engine = _load("core/engine_执行引擎.py", "core_engine_t7")
loader = _load("core/plugins_加载实例.py", "core_loader_t7")

TMP = os.path.join(tempfile.gettempdir(), "t7_records.db")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(TMP + suffix)
    except OSError:
        pass

writer = DBWriter()
BRIEF = "db=%s table=cases" % TMP

ctx1 = {"upstream": {"title": "示例一", "summary": "这是第一条通用文本。"},
        "brief": BRIEF, "note": "https://example.com/a"}
r1 = writer.execute_rich(ctx1)
check("第一次入库成功", r1["inserted"] == 1 and r1["skipped"] == 0, r1)

r2 = writer.execute_rich(ctx1)
check("同样内容第二次被跳过", r2["inserted"] == 0 and r2["skipped"] == 1, r2)

ctx2 = {"upstream": {"title": "示例二", "summary": "这是第二条通用文本。", "keywords": ["测试"]},
        "brief": BRIEF, "note": "https://example.com/b"}
r3 = writer.execute_rich(ctx2)
check("带新字段也能入库（自动加列）", r3["inserted"] == 1, r3)

conn = sqlite3.connect(TMP)
cols = [row[1] for row in conn.execute("PRAGMA table_info(cases)")]
rows = list(conn.execute("SELECT source, title, keywords FROM cases ORDER BY id"))
conn.close()

check("表里有自动长出来的 keywords 列", "keywords" in cols, cols)
check("来源被记下来了", any(r[0] == "https://example.com/a" for r in rows), rows)
check("两行数据都在", len(rows) == 2, len(rows))

# 上游只有纯文本 → 不报错，把原文存进 text 列
r_plain = writer.execute_rich({"text": "只有一段纯文本，" * 40, "brief": BRIEF,
                               "note": "https://example.com/raw"})
check("纯文本也能入库（存原文）", r_plain["inserted"] == 1, r_plain)

conn = sqlite3.connect(TMP)
cols2 = [row[1] for row in conn.execute("PRAGMA table_info(cases)")]
conn.close()
check("库里自动多出 text 列", "text" in cols2, cols2)

# 引擎真的把 upstream 传下去了
inst = loader.load_instances({
    "ai_extractor": str(Path(__file__).parent / "plugins" / "ai_extractor_字段抽取.py"),
    "db_writer": str(Path(__file__).parent / "plugins" / "db_writer_入库.py"),
})
wf = [
    {"step": "ai_extractor", "name": "抽取", "kind": "plugin", "brief": "", "order": 1, "parallel_group": ""},
    {"step": "db_writer", "name": "入库", "kind": "plugin", "brief": BRIEF, "order": 2, "parallel_group": ""},
]
rep = engine.run_workflow(wf, inst, None, "标题：示例\n摘要：这是一段通用文本。\n关键词：测试，示例")
check("流水线跑通", rep["ok"], [s["status"] for s in rep["steps"]])
db_step = rep["steps"][1]
check("入库步骤拿到 upstream 并写入",
      isinstance(db_step["output"], dict) and db_step["output"].get("inserted") == 1,
      db_step["output"])

conn = sqlite3.connect(TMP)
n = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
conn.close()
check("库里现在 4 条（3 条字段 + 1 条纯文本）", n == 4, n)

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
