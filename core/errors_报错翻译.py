# -*- coding: utf-8 -*-
"""
报错翻译（errors）
=========================================================================
把 Python 的英文报错翻译成"人话 + 怎么办"。

两种模式
-------------------------------------------------------------------------
1. 本地翻译（不花钱，任何时候都能用）
   按常见错误类型匹配：连不上、超时、没装库、找不到文件、格式不对…

2. 主模型解释（要配 Key）
   把报错 + 这一步本来要干什么 一起发给主模型，让它说"为什么错、怎么改"。
   比本地翻译准，因为只有它知道这一步的意图。

为什么两个都要？
-------------------------------------------------------------------------
* 没 Key 也得能看懂错在哪（本地翻译）
* 有 Key 时给出针对性的修法（主模型）
=========================================================================
"""

from __future__ import annotations

import re
from typing import Tuple

#: (匹配规则, 一句话原因, 建议)
RULES = [
    (
        r"ConnectionError|Connection refused|Max retries|NewConnectionError|Failed to establish|WinError 10061|actively refused|积极拒绝",
        "连不上对方服务器",
        "检查网络；如果是对内服务（Ollama/本地接口），先确认它启动了",
    ),
    (
        r"Timeout|timed out|ReadTimeout",
        "等太久了，对方没响应",
        "稍后重试；或者把超时时间调大一点",
    ),
    (
        r"HTTPError|401|403|Invalid API key|Unauthorized",
        "接口拒绝了请求（多半是 Key 不对或没权限）",
        "去选项 1 检查 API Key 是否填对、有没有余额",
    ),
    (
        r"404|Not Found",
        "地址不存在",
        "检查网址是不是打错了，或者这个页面已经删了",
    ),
    (
        r"ModuleNotFoundError|No module named",
        "缺一个 Python 库",
        "用 pip 装上它：pip install 库名（报错里会写是哪个）",
    ),
    (
        r"FileNotFoundError|No such file",
        "找不到文件",
        "检查路径对不对；文件是不是被移动或删了",
    ),
    (
        r"PermissionError|Access is denied",
        "没有权限读写这个文件",
        "换个目录；或者用管理员身份运行",
    ),
    (
        r"JSONDecodeError|Expecting value|Unterminated string",
        "返回的内容不是合法 JSON",
        "模型有时会多说几句话；建议把提示词里「只输出 JSON」再强调一遍",
    ),
    (
        r"KeyError",
        "结果里少了预期的字段",
        "看看上一步产出是不是空；或者字段名和预期不一样",
    ),
    (
        r"IndexError",
        "列表是空的，却去取第几个元素",
        "多半是上一步没搜到东西就往下走了",
    ),
    (
        r"ZeroDivisionError",
        "除以零",
        "检查数据里有没有 0 或者空值",
    ),
    (
        r"UnicodeDecodeError|codec can't decode",
        "文件编码不对（可能是 GBK 不是 UTF-8）",
        "用记事本另存为 UTF-8，或者告诉我，我加个自动识别",
    ),
    (
        r"SSL|CERTIFICATE_VERIFY_FAILED",
        "证书验证失败",
        "公司网络代理可能导致；换网络或关掉代理试试",
    ),
    (
        r"内存|MemoryError|out of memory",
        "内存不够",
        "数据太大或模型太多，关掉其它程序再试",
    ),
    (
        r"Ollama|11434",
        "本地模型服务（Ollama）没响应",
        "点一下「开始工作」会自动拉起；还不行就手动开 Ollama",
    ),
]


def explain_local(error_text: str) -> str:
    """
    把一段报错翻译成中文说明。永远有返回值（认不出就给通用建议）。
    """
    text = str(error_text or "")

    # 已经是中文的报错（插件自己抛的人话），别再套一层模板
    if re.search(r"[\u4e00-\u9fa5]{4,}", text):
        first = text.strip().splitlines()[0][:200]
        return first

    for pattern, reason, advice in RULES:
        if re.search(pattern, text, re.IGNORECASE):
            return "%s。\n建议：%s" % (reason, advice)

    # 认不出来：给出原始错误的第一行，别整段堆给用户
    first = text.strip().splitlines()[0][:160] if text.strip() else "（没有错误信息）"
    return "这一步执行失败了，但错误比较少见。\n原始信息：%s\n建议：把这段发我，或者先检查输入数据格式。" % first


def explain_with_master(master, step_name: str, brief: str, error_text: str, max_chars: int = 200) -> Tuple[bool, str]:
    """
    让主模型解释这个错该怎么修。

    返回 (成功?, 说明)
    """
    if master is None:
        return False, ""

    system = (
        "你是流水线的排错助手。用户的一步失败了，你要用中文说清："
        "①为什么失败 ②具体怎么改。控制在 3 句话内，不要客套。"
    )
    user = (
        "步骤：%s\n这一步本来要做：%s\n\n报错：\n%s"
        % (step_name, brief or "（没写备注）", str(error_text)[:1500])
    )
    try:
        text = master.chat(system, user, max_tokens=300).strip()
        return True, text[:max_chars * 3]
    except Exception as exc:
        return False, "主模型也没答上来：%s" % exc


# -------------------------------------------------------------------------
# 自测
# -------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "requests.exceptions.ConnectionError: Max retries exceeded",
        "ModuleNotFoundError: No module named 'rapidocr_onnxruntime'",
        "json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)",
        "urllib.error.URLError: <urlopen error [WinError 10061] 由于目标计算机积极拒绝>",
        "FileNotFoundError: [Errno 2] No such file or directory: 'sample.txt'",
        "某个谁也没见过的错误 xyz",
    ]
    for s in samples:
        print("·", s[:60])
        print("  →", explain_local(s).replace("\n", " "))
        print()
