# -*- coding: utf-8 -*-
"""插件：抽取式文本压缩（text_compress）。

不调用大模型：按句打分，保留信息量高的句子，按原文顺序拼回。
示例段落名是通用的（摘要/背景/方法/结果/结论），不绑定任何行业。
"""

from __future__ import annotations

import re

from base_基类 import BasePlugin

SECTION_KEYS = [
    "摘要", "背景", "方法", "结果", "结论", "建议", "要点", "正文", "附录",
    "summary", "background", "method", "result", "conclusion", "recommendation",
]

# 通用信息实体：数字、日期、比例、金额、链接
ENTITY_HINT = re.compile(
    r"(\d{2,4}[-/年]\d{1,2}|\d+(?:\.\d+)?\s*%|"
    r"(?:人民币|美元|元|万元|亿元)|\bhttps?://\S+)",
    re.I,
)

SENT_SPLIT = re.compile(r"(?<=[。！？；\n])|(?<=[.!?;])\s+")


def _sentences(text: str):
    parts = [p.strip() for p in SENT_SPLIT.split(text)]
    return [p for p in parts if p]


def _score(sentence: str, position_ratio: float) -> float:
    score = 0.0
    for key in SECTION_KEYS:
        if key.lower() in sentence.lower():
            score += 6.0
            break
    hits = len(ENTITY_HINT.findall(sentence))
    score += min(hits, 4) * 1.5
    n = len(sentence)
    if n < 6:
        score -= 4
    elif n > 120:
        score -= 2
    if position_ratio < 0.25:
        score += 1.5
    return score


class TextCompress(BasePlugin):
    """抽取式压缩：只删句，不改写。"""

    name = "文本压缩"
    default_budget = 800

    def execute(self, text_data: str) -> str:
        return self.compress(text_data, self.default_budget)

    def execute_rich(self, ctx: dict) -> dict:
        text = str(ctx.get("text") or "")
        budget = int(ctx.get("budget") or self.default_budget)
        compressed = self.compress(text, budget)
        return {
            "text": compressed,
            "original_chars": len(text),
            "compressed_chars": len(compressed),
            "ratio": round(len(compressed) / max(1, len(text)), 3),
        }

    def compress(self, text: str, budget: int = 800) -> str:
        text = str(text or "").strip()
        if len(text) <= budget:
            return text
        sents = _sentences(text)
        if not sents:
            return text[:budget]
        total = len(sents)
        scored = [(_score(s, idx / max(1, total)), idx, s) for idx, s in enumerate(sents)]
        scored.sort(key=lambda x: x[0], reverse=True)
        chosen = []
        used = 0
        for _score_value, idx, s in scored:
            if used + len(s) > budget and chosen:
                continue
            chosen.append((idx, s))
            used += len(s)
            if used >= budget * 0.95:
                break
        chosen.sort(key=lambda x: x[0])
        result = "".join(s for _idx, s in chosen)
        if len(result) > budget + 50:
            result = result[:budget] + "…"
        return result
