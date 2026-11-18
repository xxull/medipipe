# -*- coding: utf-8 -*-
"""子进程硬超时升级的回归测试。"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

from core.loader_模块加载 import load  # noqa: E402

engine = load("core/engine_执行引擎.py", "test_isolate_engine")
ok = True


def check(label, cond, detail=""):
    global ok
    print(("[PASS] " if cond else "[FAIL] ") + label + ("  " + str(detail) if detail else ""))
    if not cond:
        ok = False


wf = [{
    "step": "n1",
    "key": "text_compress",
    "name": "压缩",
    "kind": "plugin",
    "needs": {"network": False, "model": False},
    "file": str(ROOT / "plugins" / "text_compress_文本压缩.py"),
    "brief": "压缩",
    "order": 1,
    "parallel_group": "",
}]
r = engine.run_workflow(wf, plugins={}, master=None, input_text="这是一段用于测试压缩的通用文本。" * 20)
check("子进程执行成功", r["ok"], [s["status"] for s in r["steps"]])
check("子进程返回文本", bool(r["text"]), r.get("text", "")[:40])

with tempfile.TemporaryDirectory() as td:
    slow = Path(td) / "slow_plugin.py"
    slow.write_text(
        "import time\n"
        "from base_基类 import BasePlugin\n"
        "class Slow(BasePlugin):\n"
        "    name = '慢插件'\n"
        "    def execute(self, text_data):\n"
        "        time.sleep(5)\n"
        "        return text_data\n",
        encoding="utf-8",
    )
    wf2 = [{
        "step": "n2",
        "key": "slow",
        "name": "慢",
        "kind": "plugin",
        "needs": {"network": False, "model": False},
        "file": str(slow),
        "brief": "",
        "order": 1,
        "parallel_group": "",
    }]
    r2 = engine.run_workflow(wf2, plugins={}, master=None, input_text="x", step_timeout=0.8)
    check("硬超时失败", not r2["ok"], [s["status"] for s in r2["steps"]])
    check("提示子进程强制终止", "强制终止" in (r2["steps"][0].get("error") or ""), r2["steps"][0].get("error"))

print("\n结果：", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
