# -*- coding: utf-8 -*-
"""Subprocess worker for hard-timeout plugin execution.

The parent sends one JSON context on stdin.  The worker loads the plugin by
file path, executes it, and writes one marked JSON line to stdout.  Anything
the plugin prints goes to stderr so it cannot corrupt the result protocol.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(file_path: str):
    path = Path(file_path).resolve()
    spec = importlib.util.spec_from_file_location("fw_isolated_plugin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法创建插件模块：%s" % path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fw_isolated_plugin"] = module
    spec.loader.exec_module(module)
    from base_基类 import BasePlugin  # type: ignore

    for obj in vars(module).values():
        if (
            isinstance(obj, type)
            and issubclass(obj, BasePlugin)
            and obj is not BasePlugin
            and obj.__module__ == "fw_isolated_plugin"
        ):
            return obj()
    raise RuntimeError("文件里没有继承 BasePlugin 的类")


def main() -> int:
    # plugins/ 需要加入 sys.path，插件里使用的是 `from base_基类 import ...`
    plugins_dir = ROOT / "plugins"
    if str(plugins_dir) not in sys.path:
        sys.path.insert(0, str(plugins_dir))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    try:
        payload = json.loads(sys.stdin.read() or "{}")
        plugin = _load(payload.get("file", ""))
        ctx = payload.get("ctx") or {}
        with contextlib.redirect_stdout(sys.stderr):
            if hasattr(plugin, "execute_rich"):
                out = plugin.execute_rich(ctx)
            else:
                out = plugin.execute(str(ctx.get("text") or ""))
        result = {"ok": True, "output": out}
    except Exception as exc:
        result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}

    # 插件自己的 print 已经被重定向到 stderr；stdout 只留协议行。
    sys.stdout.write("\n__FW_RESULT__" + json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
