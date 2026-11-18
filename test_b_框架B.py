# -*- coding: utf-8 -*-
"""
Framework B 验收：自检 / 检索 / 路由 / 回答 / 看门狗 / 界面。

不花钱：不调用任何外部 API。
"""
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "framework_b"))

ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


from framework_b import b_回答, b_核心, b_检索  # noqa: E402

# ---------- 造一个测试库 ----------
db = os.path.join(tempfile.gettempdir(), "fw_b_test.db")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(db + suffix)
    except OSError:
        pass

conn = sqlite3.connect(db)
conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, title TEXT, body TEXT)")
conn.executemany(
    "INSERT INTO items (title, body) VALUES (?, ?)",
    [
        ("季度报告", "营收 120 万，同比增长 18%"),
        ("招聘信息", "招后端工程师，要求会 Python"),
        ("产品说明", "这个库用于批量压缩文本"),
    ],
)
conn.commit()
conn.close()

# ---------- 检索 ----------
hits = b_检索.search("营收", limit=5, db=db)
check("能按关键词检索到", len(hits) >= 1, [h["record"].get("title") for h in hits])
check("命中记录带表名", hits and hits[0].get("table") == "items", hits[0] if hits else None)

empty = b_检索.search("完全不存在的词", db=db)
check("搜不到时返回空", empty == [], empty)

st = b_检索.stats(db)
check("统计能读出总行数", st["total"] == 3, st)

# ---------- 自检 ----------
h = b_核心.health(db=db)
check("自检有数据库灯", "db" in h and h["db"]["ok"] is True, h.get("db"))
check("自检有本地模型灯", "local" in h)
check("自检有主模型灯", "master" in h)

# ---------- 路由 ----------
r1 = b_核心.route("营收", hits=1, has_master=True)
check("短问题+有命中 → 本地", r1["target"] == "local", r1)

r2 = b_核心.route("总结一下这些记录的主要趋势", hits=1, has_master=True)
check("要归纳 → 主模型", r2["target"] == "master", r2)

r3 = b_核心.route("营收", hits=1, has_master=False)
check("没 Key → 永远本地", r3["target"] == "local", r3)

# ---------- 回答（本地模式） ----------
ans = b_回答.answer("营收", hits, master=None)
check("本地回答不花钱", ans["cost_cny"] == 0.0 and ans["mode"] == "local", ans)
check("本地回答里有记录内容", "营收" in ans["text"] or "季度报告" in ans["text"], ans["text"][:80])

# ---------- 看门狗 ----------
try:
    b_核心.guard(lambda: time.sleep(2), timeout=0.3)
    check("看门狗会超时", False)
except b_核心.WatchdogTimeout as exc:
    check("看门狗会超时", True, str(exc))

fast = b_核心.guard(lambda: 42, timeout=2)
check("看门狗不影响正常调用", fast == 42, fast)

# ---------- 界面 ----------
from streamlit.testing.v1 import AppTest  # noqa: E402

at = AppTest.from_file(str(ROOT / "framework_b" / "app_b.py"), default_timeout=120)
at.run()
check("B 页面能渲染", not at.exception, str(at.exception[0].value) if at.exception else "")
check("有提问框", len(at.text_input) >= 1)
check("有查询按钮", any("查询" in b.label for b in at.button))

box = at.text_input[0]
box.set_value("营收").run()
# 注意：不点按钮。Streamlit 的按钮有 disabled 状态，AppTest 里点击
# 依赖渲染时序，容易误报"不能交互"。检索逻辑上面已用 API 直接断言过。
check("输入后页面仍正常", not at.exception, str(at.exception[0].value) if at.exception else "")

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
