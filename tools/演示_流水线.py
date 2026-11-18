# -*- coding: utf-8 -*-
"""
命令行演示：跑一条三节点流水线（不开界面）
=========================================================================
用真实的执行引擎跑：文本压缩 → 清理一下 → 格式化。
每一步的开始/结束/耗时都会打出来，能直观看到"失败即停、超时、重试"那套机制。

用法
-------------------------------------------------------------------------
    python tools\\演示_流水线.py
=========================================================================
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

from core.loader_模块加载 import load  # noqa: E402

engine = load("core/engine_执行引擎.py", "demo_engine")
loader = load("core/plugins_加载实例.py", "demo_loader")

CASE = (
    "患者男，67 岁。反复咳嗽咳痰 3 年，加重伴发热 2 天。"
    "3 天前受凉后咳黄痰，最高 38.9℃，无胸痛。高血压 10 年，吸烟 40 年。"
    "双肺可闻及湿啰音，胸片示右下肺片状影。诊断社区获得性肺炎，予抗感染。"
)

WORKFLOW = [
    {"step": "n1", "key": "text_compress", "name": "文本压缩", "kind": "plugin",
     "file": "plugins/text_compress_文本压缩.py", "order": 1, "parallel_group": ""},
    {"step": "n2", "key": "test_cleaner", "name": "清理测试", "kind": "plugin",
     "file": "plugins/test_cleaner_清理测试.py", "order": 2, "parallel_group": ""},
]


def main() -> int:
    print("① 准备画布：%d 个节点" % len(WORKFLOW))
    for w in WORKFLOW:
        print("   - %s（%s）" % (w["name"], w["key"]))

    files = {w["key"]: w["file"] for w in WORKFLOW}
    t0 = time.time()
    plugins = loader.load_instances(files)
    print("② 加载插件：%d/%d 个成功，用时 %.0f ms"
          % (len(plugins), len(files), (time.time() - t0) * 1000))

    print("③ 开始执行（失败即停，下游标 skipped）")

    def on_event(ev):
        name = ev.get("name") or ev.get("step") or ""
        if ev.get("event") == "start":
            print("   >> %s ..." % name)
        elif ev.get("event") == "end":
            mark = "ok  " if ev.get("status") == "ok" else str(ev.get("status"))
            print("   <- %-10s %s %5d ms" % (name, mark, ev.get("ms", 0)))

    t0 = time.time()
    report = engine.run_workflow(WORKFLOW, plugins=plugins, master=None,
                                 input_text=CASE, on_event=on_event,
                                 step_timeout=30, retry_max=1)
    print("④ 执行结果：%s，总耗时 %.0f ms"
          % ("成功" if report.get("ok") else "失败", (time.time() - t0) * 1000))
    for s in report.get("steps", []):
        print("   %-10s %-6s %5d ms  %s"
              % (s.get("name") or s.get("step"), s.get("status"), s.get("ms", 0),
                 str(s.get("error") or "")[:40]))

    text = str(report.get("text") or "")
    print("⑤ 最后一步的输出（前 80 字）：")
    print("   " + text[:80].replace("\n", " "))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
