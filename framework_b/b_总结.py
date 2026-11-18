# -*- coding: utf-8 -*-
"""
病历总结（b_总结）
=========================================================================
两个入口：
    文字  → 交给**主模型**（DeepSeek 等，需要 Key）提炼，2~5 秒
    图片  → 先让本机多模态模型读图（OCR / 转写），再把转写交给主模型总结

为什么默认走主模型？
------------------------------------------------------------------------
    本机 qwen3-vl:4b 是思考模型，一份病历要"想"30~60 秒，体验很差；
    主模型几秒钟就回来，质量通常还更好。所以总结要配 Key（「自检」页填）。
    没 Key 时退回本地模型，慢但能用。

输出固定六段，方便对照：
    主诉 / 现病史 / 既往史 / 关键检查 / 诊断 / 处理

纪律
------------------------------------------------------------------------
    只根据原文写，不推测、不补全、不给治疗建议。
    原文没写的段落，输出"（原文未提及）"。
=========================================================================
"""

from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path
from typing import Any, Dict

MODEL = "qwen3-vl:4b"
URL = "http://127.0.0.1:11434/api/generate"

#: 主模型用的系统提示词：角色 + 纪律（六段格式在 PROMPT 里）
MASTER_SYSTEM = (
    "你是病历整理助手。只根据用户给的病历原文提炼要点，"
    "不推测、不补全、不给治疗建议。原文里没有的信息写（原文未提及）。"
)

PROMPT = """把下面这份病历压缩成要点。严格按这个格式，每段一行：

主诉：
现病史：
既往史：
关键检查：
诊断：
处理：

要求：
1. 只写原文里有的信息，没写的写"（原文未提及）"
2. 不要推测、不要补全、不要给治疗建议
3. 每段不超过 80 字

病历原文：
---
%s
---"""


def _ollama(prompt: str, images=None, timeout: int = 300) -> str:
    payload: Dict[str, Any] = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 2500, "num_ctx": 8192},
    }
    if images:
        payload["images"] = images
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


def has_key() -> bool:
    """配了主模型 Key 吗？（和框架 A 共用 .env 的 MY_LLM_KEY）"""
    try:
        from framework_b import b_配置

        return bool(b_配置.get_key())
    except Exception:
        return False


def summarize_master(text: str) -> str:
    """用主模型总结（快）。Key 无效时抛异常，由调用方决定是否退回本地。"""
    from core.llm_主模型 import MasterLLM

    llm = MasterLLM()
    out = llm.chat(MASTER_SYSTEM, PROMPT % text[:6000], max_tokens=900, temperature=0.2)
    return (out or "").strip() or "（主模型没有返回内容）"


def read_image(path: str) -> str:
    """
    读图：让多模态模型把图片里的文字和关键信息写出来。

    这一步只做"转写"，不做总结——分开做，效果比一步到位稳。
    转写只能靠本地多模态模型（主模型读不了图片）。
    """
    p = Path(path)
    if not p.exists():
        raise RuntimeError("图片不存在：%s" % path)
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    prompt = (
        "/no_think 请把这张图片里的文字尽可能完整地转写出来（中文原样保留）。"
        "如果是病历/检查单，按 项目：数值 的形式逐行写。不要总结，不要解释。"
    )
    out = _ollama(prompt, images=[b64], timeout=300)
    return (out or "").strip()


def summarize(text: str, use_master: bool | None = None) -> str:
    """
    把病历文本提炼成六段要点。

    use_master=None 时自动判断：有 Key 就用主模型（失败退回本地），没 Key 用本地模型。
    use_master=True 表示明确要求主模型：Key 无效、断网、超预算都会把异常抛出来，
    让界面说清原因（而不是悄悄退回本地让人干等 20 秒）。
    use_master=False 强制本地模型。
    """
    t = (text or "").strip()
    if len(t) < 20:
        return "文本太短（少于 20 字），没法总结。"

    if use_master is True:
        return summarize_master(t)

    if use_master is None and has_key():
        try:
            return summarize_master(t)
        except Exception:
            pass          # 自动模式下退回本地

    out = _ollama("/no_think " + (PROMPT % t[:6000]), timeout=300)
    return (out or "").strip() or "（模型没有返回内容）"


def summarize_image(path: str) -> Dict[str, str]:
    """图片 → 转写 → 总结，两步都给出来，方便核对有没有读错。"""
    raw = read_image(path)
    return {"转写": raw, "总结": summarize(raw) if len(raw) >= 20 else "（转写内容太少）"}


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python framework_b\\b_总结.py <文本或图片路径>")
        sys.exit(0)
    arg = sys.argv[1]
    if Path(arg).exists() and Path(arg).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        r = summarize_image(arg)
        print("== 转写 ==\n%s\n\n== 总结 ==\n%s" % (r["转写"], r["总结"]))
    else:
        print(summarize(arg))
