# -*- coding: utf-8 -*-
"""
模块加载器（loader）
=========================================================================
为什么要这个文件？
-------------------------------------------------------------------------
我们的部分文件名带中文（方便人找），比如 `shell_三页外壳.py`。
Python 的 `import` 语句虽然勉强支持中文模块名，但有些工具链会出问题
（IDE 跳转、打包、pytest 收集）。

所以统一走这个 loader：**按文件路径加载，给一个 ASCII 别名注册进 sys.modules**。
这样：
    * 文件名可以是中文（方便你找）
    * 代码里引用的名字是纯英文（方便工具链）
    * 同一个文件重复加载不会产生两份模块对象（避免上次那个
      "两份 BasePlugin 导致 issubclass 全 False" 的坑）

用法
-------------------------------------------------------------------------
    from core.loader_模块加载 import load
    page1 = load("ui/page1_主模型配置.py", "ui_page1")

    # 之后其它文件也可以直接 import ui_page1（因为已经注册进 sys.modules）
=========================================================================
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 项目根目录（本文件在 core/ 下，所以往上一层）
ROOT = Path(__file__).resolve().parent.parent

# 记录"别名 → 文件绝对路径"，用来做热重载判断和重复加载检测
_LOADED: dict[str, str] = {}


def load(rel_path: str, alias: str):
    """
    按相对路径加载一个模块，用 alias 作为模块名。

    参数
    ----
    rel_path : 相对项目根目录的路径，例如 "ui/shell_三页外壳.py"
    alias    : 纯英文模块名，例如 "ui_shell"

    返回
    ----
    已加载的模块对象

    异常
    ----
    FileNotFoundError / ImportError（中文提示）
    """
    if not alias.isascii():
        raise ValueError("别名必须是纯英文：%r" % alias)

    path = (ROOT / rel_path).resolve()
    if not path.exists():
        raise FileNotFoundError("找不到模块文件：%s" % rel_path)

    # 已加载过同一个文件 → 直接返回，不再执行一遍（避免重复初始化）
    if alias in sys.modules and _LOADED.get(alias) == str(path):
        return sys.modules[alias]

    spec = importlib.util.spec_from_file_location(alias, path)
    if spec is None or spec.loader is None:
        raise ImportError("无法加载模块：%s" % rel_path)

    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        # 加载失败要清掉半成品，否则下次重试会拿到坏模块
        sys.modules.pop(alias, None)
        raise ImportError("模块 %s 加载失败（%s）：%s" % (rel_path, type(exc).__name__, exc)) from exc

    _LOADED[alias] = str(path)
    return module


def project_root() -> Path:
    """项目根目录，方便其它模块拼路径。"""
    return ROOT
