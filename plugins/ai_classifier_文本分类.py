# -*- coding: utf-8 -*-
"""插件示例：通用文本分类。

本地关键词 + 字符二元组相似度先打分；本地拿不准且配置了主模型时，
再让主模型在固定类别里选一个。它是示例插件，不代表任何行业本体。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Tuple

from base_基类 import BasePlugin

CATEGORIES: Dict[str, list] = {
    "技术": ["软件", "代码", "算法", "模型", "数据", "系统", "网络", "开发", "芯片", "人工智能"],
    "财经": ["股票", "基金", "债券", "利率", "通胀", "市场", "公司", "营收", "利润", "投资"],
    "生活": ["旅行", "美食", "教育", "家庭", "天气", "运动", "阅读", "城市", "交通", "日常"],
    "其他": [],
}

SHORT_TEXT_LIMIT = 10
CONF_MARGIN = 1.6


def _bigrams(text: str) -> Counter:
    clean = re.sub(r"[\s\u3000，。、；：！？（）()\[\]0-9a-zA-Z]", "", text)
    return Counter(clean[i : i + 2] for i in range(len(clean) - 1))


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class TextClassifier(BasePlugin):
    """通用文本分类示例：本地优先，拿不准再问主模型。"""

    name = "文本分类"
    NEEDS = {"network": False, "model": True}
    OUTPUT_FIELDS = ["category"]

    def execute(self, text_data: str) -> str:
        return self.execute_rich({"text": text_data}).get("category", "")

    def _local_score(self, text: str) -> Tuple[str, float, int]:
        text_bigrams = _bigrams(text)
        scores = {}
        hits = 0
        for category, words in CATEGORIES.items():
            n = sum(1 for w in words if w in text)
            hits += n
            proto = "，".join(words)
            scores[category] = n * 2.0 + _cosine(text_bigrams, _bigrams(proto)) * 3.0
        best = max(scores, key=lambda k: scores[k])
        return best, scores[best], hits

    def execute_rich(self, ctx: dict) -> dict:
        raw = str(ctx.get("original") or ctx.get("text") or "").strip()
        text = str(ctx.get("text") or raw).strip()
        if not raw:
            raise ValueError("分类插件收到空文本")

        if len(raw) < SHORT_TEXT_LIMIT:
            best, score, _ = self._local_score(raw)
            return {"category": best or "其他", "confidence": round(min(score / 10.0, 0.3), 2),
                    "method": "local_short", "paid": False}

        best, score, hits = self._local_score(raw)
        if hits > 0:
            return {"category": best, "confidence": round(min(score / 10.0, 0.95), 2),
                    "method": "local", "paid": False}

        master = ctx.get("master")
        if master is None:
            return {"category": best or "其他", "confidence": 0.2, "method": "local_fallback", "paid": False}

        system = (
            "你是文本分类器。只输出 JSON："
            '{"category": "类别"}。类别必须是：%s。' % "、".join(CATEGORIES)
        )
        data = master.chat_json(system, "文本片段：\n" + text[:1200], max_tokens=80)
        category = str(data.get("category") or "其他").strip()
        if category not in CATEGORIES:
            category = "其他"
        return {"category": category, "confidence": 0.6, "method": "master", "paid": True}
