# -*- coding: utf-8 -*-
"""
全局配置（config）
=========================================================================
集中放"路径、端口、上限"这类会变的东西。

为什么要单独一个文件？
-------------------------------------------------------------------------
以前 Ollama 路径、模型目录、数据库位置散落在 3 个文件里，
换台电脑就得改好几处。现在只改这里，或者用环境变量覆盖。

环境变量优先于默认值
-------------------------------------------------------------------------
    FW_HOME          项目根（一般不用改）
    FW_DB            数据库文件
    FW_OLLAMA_EXE    ollama.exe 路径
    FW_OLLAMA_BASE   Ollama 服务地址
    FW_STEP_TIMEOUT  每步超时（秒）
    FW_MAX_BATCH     批量最多跑几条
=========================================================================
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

#: 项目根目录（本文件就在根下）
BASE_DIR = Path(os.environ.get("FW_HOME") or Path(__file__).resolve().parent)

#: 数据目录（数据库、缓存都放这）
DATA_DIR = BASE_DIR / "data"

# ---------------- 数据库 ----------------
DB_PATH = os.environ.get("FW_DB") or str(DATA_DIR / "records.db")
DB_TABLE = os.environ.get("FW_DB_TABLE") or "records"

# ---------------- 本地服务 ----------------
OLLAMA_EXE = (
    os.environ.get("FW_OLLAMA_EXE")
    or shutil.which("ollama")
    or r"D:\ollama\ollama.exe"
)
OLLAMA_BASE = os.environ.get("FW_OLLAMA_BASE") or "http://127.0.0.1:11434"

#: Ollama 模型存放目录（可能有好几个，挨个找；不存在的自动跳过）


def _split_env(name: str):
    """环境变量里的多个目录：分号或系统分隔符都能拆。"""
    raw = os.environ.get(name, "") or ""
    parts = raw.replace(";", os.pathsep).split(os.pathsep)
    return [p.strip() for p in parts if p.strip()]


def _uniq(paths):
    """去重（同一个目录被环境变量和默认值写了两遍时只留一个）。"""
    seen, out = set(), []
    for p in paths:
        key = os.path.normcase(os.path.abspath(os.path.expandvars(os.path.expanduser(p))))
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


OLLAMA_STORES = _uniq(
    _split_env("FW_OLLAMA_STORE")
    + _split_env("OLLAMA_MODELS")
    + [
        r"D:\ollama\ollamaiamgers",
        r"D:\ollama\models",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\models"),
        os.path.expandvars(r"%USERPROFILE%\.ollama\models"),
    ]
)
OLLAMA_STORES = [p for p in OLLAMA_STORES if p and os.path.isdir(os.path.expandvars(p))]

#: 模型文件可能所在的目录（扫 .gguf / .safetensors 用；同样只留真实存在的）
MODEL_DIRS = _uniq(
    _split_env("FW_MODEL_DIR")
    + [
        r"D:\干活区\ComfyUI\models",
        r"D:\models",
        os.path.expanduser("~/models"),
    ]
)
MODEL_DIRS = [p for p in MODEL_DIRS if p and os.path.isdir(os.path.expandvars(p))]

# ---------------- 执行限制 ----------------
#: 单步超时（秒）。插件卡死时，超过这个时间就判失败，让流水线继续
STEP_TIMEOUT = float(os.environ.get("FW_STEP_TIMEOUT") or 180)

#: 批量最多跑多少条（防止手滑贴进几千行）
MAX_BATCH = int(os.environ.get("FW_MAX_BATCH") or 50)

#: 不需要主模型的插件是否放进子进程执行（可硬超时）
ISOLATE_PLUGINS = os.environ.get("FW_ISOLATE_PLUGINS", "1") != "0"

#: 结果存进 session 时，单段文本最多保留多少字（防内存膨胀）
KEEP_TEXT = int(os.environ.get("FW_KEEP_TEXT") or 3000)


def ensure_data_dir() -> Path:
    """确保数据目录存在，返回它。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


if __name__ == "__main__":
    print("项目根：", BASE_DIR)
    print("数据目录：", DATA_DIR)
    print("数据库：", DB_PATH)
    print("Ollama：", OLLAMA_EXE, "@", OLLAMA_BASE)
    print("超时：", STEP_TIMEOUT, "秒")
    print("批量上限：", MAX_BATCH, "条")
