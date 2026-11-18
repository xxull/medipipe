# -*- coding: utf-8 -*-
"""
应用入口（app）
=========================================================================
Streamlit 从这里启动。

这个文件**故意只有十几行**：它只负责把项目根目录加进 sys.path，
然后把 ui/shell_三页外壳.py 跑起来。

真正的功能分别在：
    ui/page1_主模型配置.py
    ui/page2_画布编排.py
    ui/page3_开始工作.py
    core/loader_模块加载.py
    plugins/*.py
=========================================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.loader_模块加载 import load  # noqa: E402

shell = load("ui/shell_三页外壳.py", "ui_shell")
shell.main()
