# -*- coding: utf-8 -*-
"""
服务启动器（launcher）
=========================================================================
执行前先探活：要用的服务没启动，就把它拉起来。

现在管两个：
    * Ollama（本地模型，端口 11434）
    * 不启动的（ComfyUI / TTS）暂时只探活不启动 —— 它们太重，
      一般由"游戏模式/全开"那套脚本负责，别在这里乱拉。

为什么单独一个文件？
-------------------------------------------------------------------------
"启动一个后台进程"这种活很容易写出坑（隐藏窗口、路径带中文、卡住不返回），
隔离在这里，出问题只影响这一个环节。
=========================================================================
"""

from __future__ import annotations

import os
import subprocess
import time
import urllib.request
from typing import Tuple

# 路径/地址统一从 config_配置.py 读（可用环境变量覆盖）
try:
    from config_配置 import OLLAMA_BASE, OLLAMA_EXE  # type: ignore
except Exception:  # 配置读不到时的兜底
    OLLAMA_EXE = r"D:\ollama\ollama.exe"
    OLLAMA_BASE = "http://127.0.0.1:11434"


def ollama_alive(timeout: float = 2.0) -> bool:
    """Ollama 服务在不在？"""
    try:
        with urllib.request.urlopen(OLLAMA_BASE + "/api/tags", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def start_ollama(wait_seconds: int = 20) -> Tuple[bool, str]:
    """
    把 Ollama 拉起来（隐藏窗口），等它就绪。

    返回 (成功?, 说明)
    """
    if ollama_alive():
        return True, "Ollama 已经在跑"

    if not os.path.exists(OLLAMA_EXE):
        return False, "找不到 Ollama：%s" % OLLAMA_EXE

    try:
        # CREATE_NO_WINDOW：别弹黑框；不等待它结束
        creation = 0x08000000 if os.name == "nt" else 0
        subprocess.Popen(
            [OLLAMA_EXE, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
            close_fds=True,
        )
    except Exception as exc:
        return False, "启动 Ollama 失败：%s" % exc

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if ollama_alive(timeout=1.0):
            return True, "Ollama 已启动"
        time.sleep(1.0)
    return False, "Ollama 启动超时（%d 秒还没响应）" % wait_seconds


def ensure_ollama(need: bool) -> Tuple[bool, str]:
    """需要就用，不需要就跳过。"""
    if not need:
        return True, ""
    return start_ollama()


def is_embedding_model(model_name: str) -> bool:
    """粗判断：是不是向量模型（不能拿来生成文字）。"""
    low = (model_name or "").lower()
    return ("bge" in low) or ("embed" in low) or ("rerank" in low)


if __name__ == "__main__":
    print("Ollama 在跑吗：", ollama_alive())
