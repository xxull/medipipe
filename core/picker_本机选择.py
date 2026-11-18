# -*- coding: utf-8 -*-
"""
本机选择器（picker）
=========================================================================
给页面提供"从我的电脑里选择"的能力。

三种情况都能用：
    1. 有图形界面 → 弹 Windows 原生"选择文件夹"对话框
    2. 弹不出来（远程/无桌面）→ 退回手输路径
    3. 用户取消 → 返回空字符串，页面什么都不做

⚠️ 为什么单独写一个文件？
    因为弹窗是"阻塞"的：框不关，程序就停在那里。
    把它隔离在这里，出问题只影响这一个按钮，不会连累整个页面。

用法
-------------------------------------------------------------------------
    from core.picker_本机选择 import pick_folder
    path = pick_folder("选择插件所在的文件夹")
=========================================================================
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional


def _pick_with_tk(title: str) -> Optional[str]:
    """用 tkinter 弹原生文件夹选择框。失败返回 None。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None

    try:
        root = tk.Tk()
        root.withdraw()                      # 隐藏主窗口，只留对话框
        root.attributes("-topmost", True)    # 保证弹在最前面
        path = filedialog.askdirectory(title=title, mustexist=True)
        root.destroy()
        return path or ""
    except Exception:
        # 没有桌面会话（比如服务账号运行）时会抛 TclError
        return None


def _pick_with_powershell(title: str) -> Optional[str]:
    """tkinter 不行时，用 PowerShell 的系统文件对话框兜底。"""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = '%s';"
        "$d.ShowNewFolderButton = $false;"
        "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }" % title.replace("'", "''")
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=180,
        )
        path = (out.stdout or "").strip()
        return path or ""
    except Exception:
        return None


def pick_folder(title: str = "选择一个文件夹") -> str:
    """
    让用户选一个文件夹，返回绝对路径。

    返回空字符串表示：用户取消，或者这台机器弹不出对话框。
    调用方拿到空字符串就什么都不做。
    """
    # 1. tkinter（大多数情况够用）
    path = _pick_with_tk(title)
    if path is not None:
        return path

    # 2. PowerShell 兜底
    path = _pick_with_powershell(title)
    if path is not None:
        return path

    return ""


def is_gui_available() -> bool:
    """粗略判断这台机器能不能弹窗（Windows 有桌面基本就有）。"""
    return os.name == "nt" and bool(os.environ.get("SESSIONNAME") or os.environ.get("USERNAME"))


def _file_with_tk(title: str, pairs) -> Optional[str]:
    """tkinter 的"打开文件"对话框。"""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return None
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(title=title, filetypes=pairs)
        root.destroy()
        return path or ""
    except Exception:
        return None


def _file_with_powershell(title: str, pattern: str) -> Optional[str]:
    """tkinter 不可用时的兜底：用 .NET 的 OpenFileDialog。"""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        "$d.Title = '%s'; $d.Filter = '%s';"
        "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.FileName }"
        % (title.replace("'", "''"), pattern.replace("'", "''"))
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            timeout=180,
        )
        return (out.stdout or "").strip()
    except Exception:
        return None


def pick_file(title: str = "选择一个文件", pattern: str = "所有文件|*.*") -> str:
    """
    弹原生"打开文件"对话框，返回选中路径；用户取消返回空串。

    pattern 用 Windows 过滤器语法，例如：
        "Python 插件|*.py|所有文件|*.*"
    """
    parts = pattern.split("|")
    pairs = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]

    p = _file_with_tk(title, pairs)
    if p is not None:
        return p
    return _file_with_powershell(title, pattern) or ""


# -------------------------------------------------------------------------
# 自测：python core/picker_本机选择.py
# -------------------------------------------------------------------------
if __name__ == "__main__":
    print("有图形界面：", is_gui_available())
    p = pick_folder("测试：选择插件文件夹")
    print("选中的路径：", repr(p))
