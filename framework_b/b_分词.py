# -*- coding: utf-8 -*-
"""
中文分词（b_分词）—— 二元切分
=========================================================================
为什么不用 trigram？
-------------------------------------------------------------------------
    SQLite 的 trigram tokenizer 要求查询至少 3 个字符，
    "胃癌""肺炎""头痛" 这种两字词永远匹配不到。

为什么用 bigram？
-------------------------------------------------------------------------
    中文没有空格，搜索引擎的通用做法是**按两字切**：

        胃癌早期表现 → 胃癌 / 癌早 / 早期 / 期表 / 表现

    查询时同样切（"胃癌" → 胃癌），直接命中倒排表。
    这是 Lucene/Elasticsearch 的 CJKAnalyzer 在用的方案，简单且有效。

英文怎么办？
-------------------------------------------------------------------------
    英文按空格和标点切词，统一小写；数字保留。
=========================================================================
"""

from __future__ import annotations

import re
from typing import List

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-z0-9]+")


def to_terms(text: str) -> List[str]:
    """
    把一段文本切成检索词（中文二元 + 英文单词）。

    返回的列表可能含重复（保留，用于词频），调用方按需去重。
    """
    s = (text or "").lower()
    terms: List[str] = []

    # 英文/数字
    terms.extend(_WORD.findall(s))

    # 中文：连续汉字串按二元切
    run: List[str] = []
    for ch in s:
        if _CJK.match(ch):
            run.append(ch)
        else:
            if len(run) >= 2:
                terms.extend("".join(run[i:i + 2]) for i in range(len(run) - 1))
            elif len(run) == 1:
                terms.append(run[0])
            run = []
    if len(run) >= 2:
        terms.extend("".join(run[i:i + 2]) for i in range(len(run) - 1))
    elif len(run) == 1:
        terms.append(run[0])

    return terms


def to_index_text(text: str) -> str:
    """建索引用：把原文变成空格分隔的词串，交给 FTS 的 unicode61 分词。"""
    return " ".join(to_terms(text))


def to_query(text: str) -> str:
    """
    查询用：同样切词，但用 OR 连接并配 bm25 排序。

    用 OR 而不是 AND：AND 要求每个词都命中，长查询容易零结果；
    OR + BM25 会把命中词多的排前面，体验更接近搜索引擎。
    """
    terms = [t for t in dict.fromkeys(to_terms(text)) if len(t) >= 2 or t.isalnum()]
    if not terms:
        return ""
    # 词里可能含引号，去掉避免破坏 MATCH 语法
    safe = [t.replace('"', "") for t in terms]
    return " OR ".join('"%s"' % t for t in safe)


if __name__ == "__main__":
    for s in ["胃癌早期表现", "Metformin Hydrochloride 500mg", "2型糖尿病"]:
        print("%-30s → %s" % (s, to_terms(s)))
