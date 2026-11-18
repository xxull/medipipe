# -*- coding: utf-8 -*-
"""
条件重试（retry）
=========================================================================
只对"重跑可能成功"的错误重试，别把时间和钱浪费在死路上。

两类错误
-------------------------------------------------------------------------
【可重试】网络抖动、超时、限流、返回不是 JSON、字段缺一半
         → 重新跑一次可能就好了

【直接失败】找不到插件、文件不存在、没权限、Key 不对、模型名写错
         → 重跑一百次也一样，直接停，把错误交给用户

重试时做什么
-------------------------------------------------------------------------
    1. 让主模型看一眼报错，给一句修法（没有主模型就跳过这步）
    2. 把修法放进 ctx["feedback"]，插件可以读到并据此调整
    3. 重新执行，最多 N 次（默认 3）

和"无脑重试"的区别
-------------------------------------------------------------------------
无脑重试会掩盖问题、白花钱；这里先判类型，再决定要不要重试。
=========================================================================
"""

from __future__ import annotations

import re
from typing import Optional

#: 这些模式说明"重跑可能有用"
RETRYABLE_PATTERNS = [
    r"timeout|timed out|超时",
    r"ConnectionError|Connection refused|ConnectionReset|连接|连不上",
    r"Temporary failure|try again|稍后重试",
    r"429|rate limit|too many requests|限流|额度",
    r"502|503|504|Bad Gateway|Service Unavailable|服务器繁忙",
    r"JSONDecodeError|Expecting value|不是合法 ?JSON|返回的格式不对",
    r"empty|为空|没有产出|空列表|字段缺",
]

#: 这些模式说明"重跑也没用"
FATAL_PATTERNS = [
    r"没找到这个插件|No module named|ModuleNotFoundError|导入失败",
    r"FileNotFoundError|文件不存在|找不到这个文件|路径",
    r"PermissionError|拒绝访问|没有权限",
    r"401|403|Invalid API key|Unauthorized|Key 不对|鉴权",
    r"模型名|model not found|unknown model",
    r"不是合法的?JSON?文件|格式不对的文件",
]


def is_retryable(error_text: str) -> bool:
    """
    判断这个错误值不值得重试。

    先看"死刑名单"：命中就直接 False（哪怕同时像网络错误，
    比如 "找不到这个文件：timeout.json" 也不该重试）。
    """
    text = str(error_text or "")
    if not text.strip():
        return False

    for p in FATAL_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return False
    for p in RETRYABLE_PATTERNS:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def ask_advice(master, step_name: str, brief: str, error_text: str) -> Optional[str]:
    """
    让主模型给一句修法（拿不到就返回 None，不影响重试）。

    刻意限制长度：只要"改哪儿"，不要长篇分析。
    """
    if master is None:
        return None
    try:
        return master.chat(
            "你是流水线的排错助手。用一句话说清这一步该怎么改，不要客套。",
            "步骤：%s\n本意：%s\n报错：%s" % (step_name, brief or "（无）", str(error_text)[:800]),
            max_tokens=120,
        ).strip() or None
    except Exception:
        return None


def category(error_text: str) -> str:
    """给界面用的一句话分类。"""
    if not str(error_text or "").strip():
        return "无错误信息"
    return "可重试" if is_retryable(error_text) else "不可重试"


if __name__ == "__main__":
    samples = [
        "requests.exceptions.ConnectionError: Max retries exceeded",
        "json.decoder.JSONDecodeError: Expecting value",
        "没找到这个插件（可能被移动或改名了）：x",
        "FileNotFoundError: [Errno 2] No such file",
        "HTTPError: 503 Service Unavailable",
        "401 Unauthorized: Invalid API key",
    ]
    for s in samples:
        print("%-6s %s" % (category(s), s))
