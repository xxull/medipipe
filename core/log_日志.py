# -*- coding: utf-8 -*-
"""
运行日志（log）
=========================================================================
把每一步的执行情况写进 data/app.log，关掉页面也能查。

为什么要单独一个文件？
-------------------------------------------------------------------------
页面上的日志只在内存里，刷新就没；出了问题你只能靠回忆。
落盘之后：
    * 事后能查"昨晚上那一轮到底哪一步挂了"
    * 能统计"哪一步最慢/最贵"
    * 出问题时直接把最后几十行贴出来就能定位

设计取舍
-------------------------------------------------------------------------
    * 单文件 + 大小上限（默认 5 MB），超了就滚动成 app.log.1，不写轮转库
    * 每行都是 JSON，方便以后拿脚本统计，也方便人肉看
    * 写失败绝不影响主流程（日志不能成为新的故障点）
=========================================================================
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

# 默认放项目 data/ 下
try:
    from config_配置 import DATA_DIR  # type: ignore

    LOG_DIR = Path(DATA_DIR)
except Exception:  # pragma: no cover
    LOG_DIR = Path(__file__).resolve().parent.parent / "data"

LOG_PATH = LOG_DIR / "app.log"
MAX_BYTES = 5 * 1024 * 1024     # 5 MB 滚动一次

_lock = threading.Lock()


def _rotate_if_needed() -> None:
    """文件太大就挪成 .1（只留一份历史，够用）。"""
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > MAX_BYTES:
            old = LOG_PATH.with_suffix(".log.1")
            if old.exists():
                old.unlink()
            LOG_PATH.rename(old)
    except Exception:
        pass


def log_event(event: str, **fields: Any) -> None:
    """
    写一条日志。

    参数
    ----
    event  : 事件名，比如 run_start / step_end / run_end / degrade
    fields : 任意附加字段（会被塞进同一行 JSON）
    """
    line = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event}
    for k, v in fields.items():
        # 太长的值截断，日志不该被一篇文章撑爆
        if isinstance(v, str) and len(v) > 300:
            v = v[:300] + "…"
        line[k] = v

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with _lock:
            _rotate_if_needed()
            with open(LOG_PATH, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    except Exception:
        # 日志写不进去也不能影响干活
        pass


def tail(n: int = 50) -> str:
    """读最后 n 行（界面上"查看日志"用）。"""
    try:
        if not LOG_PATH.exists():
            return "（还没有日志）"
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fp:
            lines = fp.readlines()
        return "".join(lines[-n:]) or "（日志是空的）"
    except Exception as exc:
        return "读日志失败：%s" % exc


def path() -> str:
    return str(LOG_PATH)


if __name__ == "__main__":
    log_event("selftest", note="这是一条测试", n=1)
    print("日志文件：", path())
    print(tail(3))
