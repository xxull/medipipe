# -*- coding: utf-8 -*-
"""
Framework B · 自检 / 路由 / 看门狗（b_核心）
=========================================================================
三个小组件放一个文件，因为它们都很短，而且总是配合使用。

    自检 health()      启动时确认：数据库能读、本地模型在、主模型 Key 有
    路由 route()       判断这次问题该"本地应付"还是"请主模型"
    看门狗 guard()    给一次调用套超时，超时就抛异常，绝不干等

原则
-------------------------------------------------------------------------
    任何一项检查失败都不该让页面崩：返回"红灯 + 原因"，用户自己判断要不要继续。
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

import os
import threading
import time
from typing import Any, Callable, Dict, Optional


# -------------------------------------------------------------------------
# 自检
# -------------------------------------------------------------------------
def health(db: Optional[str] = None) -> Dict[str, Any]:
    """
    返回三个灯的状态：

        db      数据库能不能读
        local   本地模型在不在（Ollama）
        master  主模型 Key 有没有配

    每项都是 {"ok": bool, "detail": str}
    """
    out: Dict[str, Any] = {}

    # 数据库
    try:
        from framework_b.b_检索 import stats

        st = stats(db)
        if st["exists"]:
            total = format(st["total"], ",")
            approx = "" if st.get("exact", True) else "（部分为估算）"
            out["db"] = {"ok": True,
                         "detail": "共 %s 条%s，%d 张表" % (total, approx, len(st["tables"]))}
        else:
            out["db"] = {"ok": False, "detail": "库文件不存在：%s" % st["db"]}
    except Exception as exc:
        out["db"] = {"ok": False, "detail": "读库失败：%s" % exc}

    # 本地模型
    try:
        from core.launcher_服务启动 import ollama_alive

        out["local"] = (
            {"ok": True, "detail": "Ollama 在线"}
            if ollama_alive()
            else {"ok": False, "detail": "Ollama 没响应（本地检索仍可用）"}
        )
    except Exception as exc:
        out["local"] = {"ok": False, "detail": "检查失败：%s" % exc}

    # 主模型 Key（和选项 1 用同一套读取顺序）
    try:
        key = (
            os.environ.get("MY_LLM_KEY")
            or os.environ.get("MAIN_LLM_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or ""
        )
        out["master"] = (
            {"ok": bool(key), "detail": "已配置" if key else "没配 Key（只能用本地检索）"}
        )
    except Exception as exc:
        out["master"] = {"ok": False, "detail": "检查失败：%s" % exc}

    return out


# -------------------------------------------------------------------------
# 路由
# -------------------------------------------------------------------------
def route(question: str, hits: int = 0, has_master: bool = True) -> Dict[str, Any]:
    """
    决定谁来回答：

        local   问题短 + 库里有命中 → 直接把记录给你，不花钱
        master  问题长/要归纳/库里的东西不够 → 请主模型

    判据刻意简单（能被解释）：
        * 少于 12 个字，且检索有结果 → 本地
        * 含"总结/分析/对比/为什么/建议"这类词 → 主模型
        * 没有主模型 Key → 永远本地
    """
    q = (question or "").strip()
    if not has_master:
        return {"target": "local", "reason": "没配主模型 Key，走本地检索"}

    heavy_words = ("总结", "分析", "对比", "为什么", "建议", "归纳", "评价", "推理", "比较")
    if any(w in q for w in heavy_words):
        return {"target": "master", "reason": "问题需要归纳/对比，交给主模型"}

    if len(q) >= 12:
        return {"target": "master", "reason": "问题较长（%d 字），交给主模型理解" % len(q)}

    if hits <= 0:
        return {"target": "master", "reason": "本地没检索到相关内容，请主模型兜底"}

    return {"target": "local", "reason": "短问题 + 本地有命中，直接给结果"}


# -------------------------------------------------------------------------
# 看门狗
# -------------------------------------------------------------------------
class WatchdogTimeout(TimeoutError):
    """超时了。"""


def guard(fn: Callable[[], Any], timeout: float = 30.0) -> Any:
    """
    跑 fn，超过 timeout 秒就抛 WatchdogTimeout。

    说明：Python 线程杀不掉，所以这里只是"不再等它"，主流程能继续。
    真正的硬杀要靠子进程（Framework A 的插件隔离就是这么做的）。
    """
    box: Dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    t = threading.Thread(target=target, daemon=True)
    t0 = time.perf_counter()
    t.start()
    t.join(timeout)
    elapsed = time.perf_counter() - t0

    if t.is_alive():
        raise WatchdogTimeout("超过 %.1f 秒没返回（等了 %.1f 秒）" % (timeout, elapsed))
    if "error" in box:
        raise box["error"]
    return box.get("value")


if __name__ == "__main__":
    import json

    print(json.dumps(health(), ensure_ascii=False, indent=2))
    print(route("总结一下最近入库的数据", hits=3))
    print(route("查询 123", hits=3))
    try:
        guard(lambda: time.sleep(2), timeout=0.5)
    except WatchdogTimeout as exc:
        print("看门狗生效：", exc)
