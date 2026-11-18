# -*- coding: utf-8 -*-
"""
Framework B · 回答生成（b_回答）
=========================================================================
两条路，按路由结果走：

    local   把检索到的记录整理成一段可读的结果，不调用任何 API
    master  把记录当"资料"，请主模型基于资料回答，并明确要求：
            只根据资料说，资料里没有的就直说没有

为什么强调"资料里没有就说没有"？
-------------------------------------------------------------------------
    不这么写，模型会自己编。框架里最忌讳"看起来答了，其实是瞎编"。
=========================================================================
"""

from __future__ import annotations

# 让"单独运行这个文件"和"被 app_b 导入"都能找到模块
import sys as _sys
from pathlib import Path as _Path

_ROOT = _Path(__file__).resolve().parent.parent
for _p in (str(_ROOT), str(_ROOT / "framework_b")):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from typing import Any, Dict, List

MAX_DOC_CHARS = 1200      # 每条记录塞给模型的长度上限


def format_local(question: str, hits: List[Dict[str, Any]], limit: int = 5) -> str:
    """本地模式：老实把命中的记录摆出来。"""
    if not hits:
        return "没有检索到相关内容。\n可以换个关键词，或者先去「Framework A」把这批数据生产出来。"

    lines = ["共找到 %d 条（本地模式，未调用模型）：" % len(hits)]
    for i, h in enumerate(hits[:limit], start=1):
        rec = h.get("record") or {}
        # 只展示前面几个字段，太长没意义
        parts = []
        for k, v in list(rec.items())[:6]:
            if k in ("id", "fingerprint"):
                continue
            text = str(v) if v is not None else ""
            parts.append("%s=%s" % (k, text[:80]))
        lines.append("%d. [%s] %s" % (i, h.get("table", "?"), "；".join(parts)))
    return "\n".join(lines)


def build_context(hits: List[Dict[str, Any]], limit: int = 5) -> str:
    """把检索结果拼成给主模型看的资料块。"""
    blocks = []
    for i, h in enumerate(hits[:limit], start=1):
        rec = h.get("record") or {}
        body = "\n".join(
            "%s: %s" % (k, str(v)[:300]) for k, v in rec.items() if k not in ("id", "fingerprint")
        )
        blocks.append("【资料 %d】（表 %s）\n%s" % (i, h.get("table", "?"), body[:MAX_DOC_CHARS]))
    return "\n\n".join(blocks)


def answer(question: str, hits: List[Dict[str, Any]], master=None,
           timeout: float = 30.0) -> Dict[str, Any]:
    """
    生成回答。返回 {"text", "mode", "cost_cny", "ms"}。

    master 为 None 时走本地模式。
    """
    import time

    t0 = time.perf_counter()

    if master is None:
        text = format_local(question, hits)
        return {
            "text": text,
            "mode": "local",
            "cost_cny": 0.0,
            "ms": int((time.perf_counter() - t0) * 1000),
        }

    from framework_b.b_核心 import guard

    context = build_context(hits)
    system = (
        "你是一个数据检索助手。只根据【资料】回答，不要补充资料以外的内容；"
        "资料里没有的，直接说“资料里没有”。回答用中文，先给结论再给依据。"
    )
    user = "【问题】%s\n\n【资料】\n%s" % (question, context or "（没有检索到资料）")

    try:
        text = guard(lambda: master.chat(system, user, max_tokens=600), timeout=timeout)
        mode = "master"
    except Exception as exc:
        # 主模型挂了就降级：别让页面白屏，把本地结果给出去
        text = "（主模型不可用：%s）\n\n%s" % (exc, format_local(question, hits))
        mode = "degraded"

    usage = getattr(master, "usage", None)
    cost = 0.0
    try:
        if usage is not None:
            cost = float(usage.as_dict().get("cost_cny", 0))
    except Exception:
        pass

    return {
        "text": text,
        "mode": mode,
        "cost_cny": cost,
        "ms": int((time.perf_counter() - t0) * 1000),
    }


def make_master():
    """按环境变量里的 Key 建主模型客户端；没 Key 返回 None。"""
    import os

    key = (
        os.environ.get("MY_LLM_KEY")
        or os.environ.get("MAIN_LLM_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
        or ""
    )
    if not key:
        return None
    try:
        from core.llm_主模型 import MasterLLM

        return MasterLLM(key=key, budget_cny=0.2, timeout=30)
    except Exception:
        return None


if __name__ == "__main__":
    demo_hits = [{"table": "demo", "record": {"title": "示例记录", "text": "这是一段示例内容"}}]
    print(answer("这讲的是什么", demo_hits, master=None)["text"])
