# -*- coding: utf-8 -*-
"""
插件实例加载（plugin instances）
=========================================================================
画布上写的是插件"名字"，执行时需要真正的对象。
这个文件负责：按文件路径把插件 import 进来、实例化、交给执行引擎。

⚠️ 踩过的坑
-------------------------------------------------------------------------
用 `from plugins.base import BasePlugin` 和插件的 `from base_基类 import BasePlugin`
会得到**两个不同的类对象**，issubclass 全 False，一个插件都加载不上。
所以这里统一用 `base`（不是 `plugins.base`），并且把 plugins 目录加进 sys.path。
=========================================================================
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"

# 保证 `from base_基类 import BasePlugin` 能用
if str(PLUGINS_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGINS_DIR))

from base_基类 import BasePlugin  # noqa: E402

#: 最近一次加载失败的 alias -> 人话错误（页面会展示，方便定位缺依赖/语法错误）
LAST_ERRORS: Dict[str, str] = {}


def load_one(file_path: str, alias: str) -> Optional[Any]:
    """从一个 .py 文件加载插件实例。失败返回 None，并在 LAST_ERRORS 里留下原因。"""
    path = Path(file_path)
    if not path.exists():
        LAST_ERRORS[alias] = "文件不存在：%s" % path
        return None

    module_name = "fw_plugin_" + alias
    try:
        if module_name in sys.modules:
            module = sys.modules[module_name]
        else:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                LAST_ERRORS[alias] = "无法创建模块 spec"
                return None
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, BasePlugin)
                and obj is not BasePlugin
                and obj.__module__ == module_name
            ):
                return obj()
        LAST_ERRORS[alias] = "文件里没有找到继承 BasePlugin 的类"
    except Exception as exc:
        sys.modules.pop(module_name, None)
        LAST_ERRORS[alias] = "%s: %s" % (type(exc).__name__, exc)
        return None
    return None


def load_instances(plugin_files: Dict[str, str]) -> Dict[str, Any]:
    """
    批量加载。

    参数：{插件 key: 文件路径}
    返回：{插件 key: 插件实例}
    """
    out: Dict[str, Any] = {}
    LAST_ERRORS.clear()
    for key, file_path in (plugin_files or {}).items():
        inst = load_one(file_path, key)
        if inst is not None:
            out[key] = inst
    return out
