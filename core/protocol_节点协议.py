# -*- coding: utf-8 -*-
"""
节点数据协议（protocol_节点协议）
=========================================================================
解决的问题
-------------------------------------------------------------------------
    画布上节点是自由连的。A 的输出字段如果 B 用不上（或名字写错），
    以前要等跑起来报错才发现，而且报错信息是"KeyError: xxx"，很难懂。

    现在每个插件声明自己需要什么（REQUIRES），也声明产出什么
    （OUTPUT_FIELDS，基类已有）。运行前先对一遍：

        upstream 有 → 放行
        upstream 没有但可以兜底（比如有 text）→ 放行 + 记一条警告
        完全没有 → 报"缺字段"，明确指出是谁缺、上游给了什么
=========================================================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def describe(plugin) -> Dict[str, Any]:
    """把一个插件的能力说清楚（给界面/日志用）。"""
    return {
        "name": getattr(plugin, "name", plugin.__class__.__name__),
        "requires": list(getattr(plugin, "REQUIRES", []) or []),
        "outputs": list(getattr(plugin, "OUTPUT_FIELDS", []) or ["text"]),
        "needs_network": bool((getattr(plugin, "NEEDS", {}) or {}).get("network")),
        "needs_model": bool((getattr(plugin, "NEEDS", {}) or {}).get("model")),
    }


def check(plugin, ctx: Dict[str, Any]) -> Tuple[bool, str]:
    """
    检查这一步能不能跑。

    返回 (能不能跑, 说明)

    规则：
        * 插件没声明 REQUIRES → 一律放行（老插件不用改）
        * 声明的字段都要能在 ctx（含 upstream）里找到
        * 缺字段但 ctx 里有 text → 放行，返回警告
        * 都没有 → 拦住，返回缺什么
    """
    requires = list(getattr(plugin, "REQUIRES", []) or [])
    if not requires:
        return True, ""

    upstream = ctx.get("upstream") or {}
    available = set()
    if isinstance(upstream, dict):
        available |= {str(k) for k, v in upstream.items() if v not in (None, "", [], {})}
    for key in ("text", "original", "input", "brief", "note"):
        if ctx.get(key):
            available.add(key if key != "original" else "text")

    missing = [r for r in requires if r not in available]
    if not missing:
        return True, ""

    if ctx.get("text"):
        return True, "缺字段 %s，退化为用整段文本（可能不准）" % "、".join(missing)

    return False, "缺必需字段：%s；上游只给了 %s" % (
        "、".join(missing),
        "、".join(sorted(available)) or "空",
    )


def suggest_edges(plugins: Dict[str, Any]) -> List[str]:
    """
    粗略检查：哪些插件的产出，没人接。

    返回中文提示列表（给画布页的"检查连线"按钮用）。
    """
    warnings = []
    produced: Dict[str, str] = {}
    for key, p in plugins.items():
        for f in describe(p)["outputs"]:
            produced.setdefault(f, key)

    consumed = set()
    for p in plugins.values():
        consumed |= set(describe(p)["requires"])

    for field_name, owner in produced.items():
        if field_name in ("text",):
            continue
        if field_name not in consumed:
            warnings.append("「%s」产出了 %s，但没有节点使用它" % (owner, field_name))
    return warnings
