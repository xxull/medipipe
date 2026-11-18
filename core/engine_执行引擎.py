# -*- coding: utf-8 -*-
"""
执行引擎（engine）
=========================================================================
把画布生成的 JSON 变成"真的会跑"的东西。

输入：workflow（画布产出的步骤列表）
输出：每一步的状态、耗时、产出，以及整轮的汇总

三条执行规则
-------------------------------------------------------------------------
1. **串行**：按 order 顺序执行，前一步的产出交给后一步
2. **并行**：parallel_group 相同的步骤同时跑（线程池），各自拿到同一份输入，
   跑完把结果拼起来给下游
3. **主模型节点**：不处理数据，只"看一眼 + 说句话"（检查/报错/验收）。
   它的输出会作为这一步的结果记下来，但不会覆盖数据本身。

为什么不用 asyncio？
-------------------------------------------------------------------------
插件都是同步的（requests、文件读写），asyncio 包一层还得 to_thread，
本质还是线程。这里直接用线程池，行为更可预测，也更好调试。
=========================================================================
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

MAX_PARALLEL = 4

# 日志与条件重试（单独的模块，导入失败也不该让引擎起不来）
try:
    from core.log_日志 import log_event
except Exception:  # pragma: no cover
    def log_event(*_a, **_kw):  # type: ignore
        return None

try:
    from core.retry_重试 import ask_advice, is_retryable
except Exception:  # pragma: no cover
    def is_retryable(_e):  # type: ignore
        return False

    def ask_advice(*_a, **_kw):  # type: ignore
        return None


class Degraded(Exception):
    """主模型不可用时的"降级"信号：不算失败，算"这步没做"。"""


def _short(text: Any, n: int = 400) -> str:
    """把产出压成一段便于显示的短文本。"""
    if text is None:
        return ""
    if isinstance(text, str):
        s = text.strip()
    else:
        try:
            s = json.dumps(text, ensure_ascii=False)
        except Exception:
            s = str(text)
    s = s.replace("\n", " ")
    return s[:n]


def _result_text(output: Any) -> str:
    """从插件产出里取出"文本"，交给下一步。"""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        for k in ("text", "output", "content", "result"):
            v = output.get(k)
            if isinstance(v, str) and v.strip():
                return v
        try:
            return json.dumps(output, ensure_ascii=False)
        except Exception:
            return str(output)
    return "" if output is None else str(output)


class StepReport(dict):
    """一步的结果（用 dict 子类，方便直接进 JSON）。"""

    def __init__(self, step: str, name: str, kind: str, brief: str = "", note: str = ""):
        super().__init__()
        self.update(
            {
                "step": step,
                "name": name,
                "kind": kind,
                "brief": brief,
                "note": note,
                "status": "pending",
                "ms": 0,
                "output": None,
                "text": "",
                "error": "",
                "skipped": "",
                "retries": 0,        # 重试了几次
                "advice": "",        # 主模型给的修法（重试时用）
            }
        )


def _run_master_node(master, brief: str, note: str, upstream: str) -> str:
    """主模型节点：只看、只点评，不处理数据。"""
    if master is None:
        # 降级而不是失败：没配 Key 时，不该让一个"监督节点"把整条流水线拖红
        raise Degraded("没有配置主模型，监督节点已跳过")
    instruction = (brief or note or "检查上一步的结果有没有问题").strip()
    user = (
        "【这一步要你做的事】%s\n\n"
        "【上游产出（可能很长，已截断）】\n%s"
        % (instruction, _short(upstream, 1200))
    )
    return master.chat(
        "你是流水线的监督者。只做检查/点评/纠错，不要重写数据，回答控制在 120 字内。",
        user,
        max_tokens=260,
    )


def _run_model_node(model_name: str, brief: str, text: str, timeout: int = 60) -> str:
    """
    轻量模型节点：调本地 Ollama 生成。

    embedding 类模型（bge-m3）不能当生成模型用，会直接报错，
    这里提前挡掉，给一句人话。
    """
    import urllib.request

    if not model_name:
        raise RuntimeError("这个模型节点没指定具体模型")

    if "bge" in model_name.lower() or "embed" in model_name.lower():
        raise RuntimeError("这是向量模型，不能拿来生成文字（换 qwen 之类的生成模型）")

    try:
        from config_配置 import OLLAMA_BASE
    except Exception:
        OLLAMA_BASE = "http://127.0.0.1:11434"

    prompt = (brief or "处理下面的内容") + "\n\n" + (text or "")
    payload = json.dumps({"model": model_name, "prompt": prompt, "stream": False}).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_BASE.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return str(data.get("response") or "").strip()
    except Exception as exc:
        raise RuntimeError("本地模型没跑起来（Ollama 开了吗）：%s" % exc)


def _should_isolate(item: Dict[str, Any]) -> bool:
    """是否需要放进子进程硬超时执行。

    只隔离“明确不需要主模型”的插件；需要 master 的插件仍在线程里跑，
    因为 master 客户端不能安全地跨进程序列化。
    """
    if os.environ.get("FW_ISOLATE_PLUGINS", "1") == "0":
        return False
    needs = item.get("needs")
    if not isinstance(needs, dict):
        return False
    if needs.get("model"):
        return False
    file_path = item.get("file")
    return bool(file_path and Path(file_path).is_file())


def _run_plugin_isolated(item: Dict[str, Any], ctx: Dict[str, Any], timeout: float) -> Any:
    """在独立 Python 进程里执行插件，超时直接 kill。"""
    payload = {
        "file": str(Path(item["file"]).resolve()),
        "ctx": {k: v for k, v in ctx.items() if k != "master"},
    }
    body = json.dumps(payload, ensure_ascii=False, default=str)
    worker = Path(__file__).with_name("worker_插件.py")
    root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        [sys.executable, str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(root),
    )
    try:
        out, err = proc.communicate(body, timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(
            "这一步超过 %.1f 秒，子进程已强制终止（硬超时）" % timeout
        ) from None

    result = None
    for line in reversed((out or "").splitlines()):
        if line.startswith("__FW_RESULT__"):
            try:
                result = json.loads(line[len("__FW_RESULT__"):])
            except json.JSONDecodeError:
                result = None
            break
    if result is None:
        tail = (err or out or "").strip()[-300:]
        raise RuntimeError("插件子进程没有返回结果（退出码 %s）：%s" % (proc.returncode, tail))
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "插件子进程执行失败")
    return result.get("output")


def run_workflow(
    workflow: List[Dict[str, Any]],
    plugins: Dict[str, Any],
    master=None,
    input_text: str = "",
    logger: Optional[Callable[[str], None]] = None,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    step_timeout: float = 180.0,
    retry_max: int = 0,
) -> Dict[str, Any]:
    """
    执行整条流水线。

    参数
    ----
    workflow   : 画布产出的步骤列表（含 step/name/kind/brief/note/order/parallel_group）
    plugins    : {插件 key: 插件实例}
    master     : 主模型客户端（没有就跳过监督节点）
    input_text : 原始输入（文本或网址）
    logger     : 日志回调（页面传 st.status.write）

    返回：{"ok": bool, "steps": [...], "ms": int, "text": 最终文本}
    """
    def log(msg: str) -> None:
        if logger:
            logger(msg)

    def emit(**kw: Any) -> None:
        """把"某一步开始/结束"的通知发给页面，用来点亮状态灯。"""
        if on_event:
            try:
                on_event(kw)
            except Exception:
                pass

    if not workflow:
        return {"ok": False, "steps": [], "ms": 0, "text": "", "error": "画布是空的"}

    steps: List[StepReport] = []
    current_text = input_text          # 数据在步骤之间传递（可能被压缩）
    # 原始全文：抓取类插件拿回来的那份。压缩之后 current_text 会变短，
    # 但"抽取字段"这类插件需要看没被压缩过的原文，所以单独记一份。
    source_text = ""
    # 最近一次返回 dict 的步骤产出（入库/校验类插件需要它）
    last_structured: Dict[str, Any] = {}
    started = time.time()

    # 按 order 排序（画布已经给好了，这里再保险一次）
    ordered = sorted(workflow, key=lambda w: w.get("order", 0))

    # 并行分组：把"同组且相邻"的步骤攒成一批
    batches: List[List[Dict[str, Any]]] = []
    for item in ordered:
        group = item.get("parallel_group") or ""
        if group and batches and batches[-1] and (batches[-1][0].get("parallel_group") == group):
            batches[-1].append(item)
        else:
            batches.append([item])

    # 某一步失败后，后面的步骤不再执行（标记为 skipped）
    stopped = False

    for batch in batches:
        is_parallel = len(batch) > 1

        # 每一步开始时的快照：避免闭包读到循环后面被改掉的变量（ruff B023）
        snap_text = current_text
        snap_source = source_text or input_text
        snap_structured = dict(last_structured)

        # 用默认参数把快照"钉住"，避免闭包读循环变量（ruff B023）
        def exec_one(item: Dict[str, Any], _text=snap_text, _source=snap_source,
                     _structured=snap_structured, _feedback: str = "") -> StepReport:
            rep = StepReport(
                step=item.get("step", ""),
                name=item.get("name", ""),
                kind=item.get("kind", ""),
                brief=item.get("brief", ""),
                note=item.get("note", ""),
            )
            t0 = time.perf_counter()
            try:
                kind = item.get("kind")
                if kind == "master":
                    out = _run_master_node(master, item.get("brief", ""), item.get("note", ""), _text)
                elif kind == "model":
                    out = _run_model_node(item.get("model", ""), item.get("brief", ""), _text)
                elif kind == "plugin":
                    ctx = {
                        "text": _text,
                        # 优先给"抓回来的全文"；还没有就退回用户输入
                        "original": _source,
                        # 上一步的结构化产出（dict）
                        "upstream": dict(_structured),
                        # 用户最初给的输入（网址或文本），入库记来源要用
                        "input": input_text,
                        "master": master,
                        "brief": item.get("brief", ""),
                        "note": item.get("note", ""),
                        # 重试时主模型给的修法，插件可以读它调整行为
                        "feedback": _feedback,
                    }
                    if _should_isolate(item):
                        # 非模型插件：子进程执行，超时可硬杀。
                        # 给子进程略短于外层线程的预算，确保先由子进程报"强制终止"，
                        # 而不是外层线程先把结果判成"后台线程可能还在跑"。
                        child_timeout = max(0.1, float(step_timeout) - 0.2)
                        out = _run_plugin_isolated(item, ctx, child_timeout)
                    else:
                        inst = plugins.get(item.get("key")) or plugins.get(item.get("step"))
                        if inst is None:
                            raise RuntimeError("没找到这个插件（可能被移动或改名了）：%s" % item.get("step"))

                        # 节点协议检查：插件声明了 REQUIRES 就先对一遍上游字段，
                        # 缺了在跑之前就说清楚，而不是等 KeyError。
                        try:
                            from core.protocol_节点协议 import check as _proto_check

                            _ok, _why = _proto_check(inst, ctx)
                            if not _ok:
                                raise RuntimeError("节点协议检查未通过：%s" % _why)
                            if _why:
                                log("     ⚠ %s" % _why)
                        except ImportError:
                            pass

                        # 优先用 execute_rich（能返回结构化结果）
                        if hasattr(inst, "execute_rich"):
                            out = inst.execute_rich(ctx)
                        else:
                            out = inst.execute(_text)
                else:
                    raise RuntimeError("不认识的任务类型：%s" % kind)

                rep["output"] = out if isinstance(out, (dict, list)) else str(out)
                rep["text"] = _result_text(out)
                rep["status"] = "ok"
            except Degraded as exc:
                # 主模型不可用：这是"没做"，不是"做错了"，别标红
                rep["status"] = "degraded"
                rep["error"] = str(exc)
            except Exception as exc:
                rep["status"] = "failed"
                rep["error"] = str(exc)
            rep["ms"] = int((time.perf_counter() - t0) * 1000)
            return rep

        def run_guarded(item: Dict[str, Any]) -> StepReport:
            """
            带超时地跑一步。

            为什么要这个：插件里可能有死循环、卡死的网络请求、等待输入的弹窗。
            没有超时的话，整条流水线会一直挂着，页面上永远转圈。
            Python 没法强行杀掉线程，所以超时后把这一步判失败，
            让主线继续走（那个线程自己会结束，不会阻塞进程退出）。
            """
            box: Dict[str, Any] = {}

            def target() -> None:
                try:
                    box["rep"] = exec_one(item)
                except BaseException as exc:  # 插件抛 SystemExit 之类也要接住
                    box["exc"] = exc

            t = threading.Thread(target=target, daemon=True)
            t.start()
            t.join(step_timeout)

            if t.is_alive():
                rep = StepReport(
                    step=item.get("step", ""),
                    name=item.get("name", ""),
                    kind=item.get("kind", ""),
                    brief=item.get("brief", ""),
                    note=item.get("note", ""),
                )
                rep["status"] = "failed"
                rep["error"] = (
                    "这一步超过 %d 秒没返回，流水线已跳过（可能是网络卡住或不支持超时的库）。"
                    "注意：Python 线程无法被强杀，后台线程可能仍在收尾。"
                ) % step_timeout
                rep["ms"] = int(step_timeout * 1000)
                return rep

            if "exc" in box:
                raise box["exc"]
            rep = box["rep"]

            # ---- 条件重试（只对"重跑可能有用"的错误）----
            # 判据在 core/retry_重试.py：网络/超时/限流/JSON 坏 → 重试；
            # 缺插件/文件不存在/Key 不对 → 直接失败，重跑一百次也一样。
            if (
                rep.get("status") == "failed"
                and int(retry_max) > 0
                and is_retryable(rep.get("error", ""))
            ):
                for attempt in range(1, int(retry_max) + 1):
                    advice = ask_advice(master, rep.get("name", ""), rep.get("brief", ""),
                                        rep.get("error", ""))
                    rep["advice"] = advice or ""
                    log("  ↻ 第 %d 次重试（%s）%s" % (
                        attempt,
                        "可重试错误" if advice is None else "主模型给了修法",
                        ("：" + advice[:60]) if advice else "",
                    ))
                    log_event("retry", step=rep.get("step"), name=rep.get("name"),
                              attempt=attempt, error=rep.get("error", "")[:200],
                              advice=(advice or "")[:200])

                    again = exec_one(item, _feedback=advice or "")
                    again["retries"] = attempt
                    again["advice"] = advice or ""
                    rep = again
                    if rep.get("status") in ("ok", "degraded"):
                        break

            return rep

        # 通知页面：这些步骤开始跑了（黄灯）
        for item in batch:
            emit(event="start", step=item.get("step", ""), name=item.get("name", ""), order=item.get("order", 0))

        if is_parallel:
            names = "、".join(i.get("name", "?") for i in batch)
            log("⚡ 并行执行 %d 步：%s" % (len(batch), names))
            with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL, len(batch))) as pool:
                results = list(pool.map(run_guarded, batch))
            # 并行结果拼起来，作为下一步的输入
            merged = "\n\n".join(r["text"] for r in results if r["text"])
            if merged:
                current_text = merged
        else:
            item = batch[0]
            log("▶ %s（%s）%s" % (item.get("name", "?"), item.get("tag", item.get("kind", "")),
                                 ("：" + item["brief"]) if item.get("brief") else ""))
            rep = run_guarded(item)
            results = [rep]
            if rep["status"] == "ok" and rep["text"]:
                current_text = rep["text"]

        for r in results:
            steps.append(r)
            # 记录最长的文本当"原始全文"（抓取结果通常最长）
            if len(r.get("text") or "") > len(source_text):
                source_text = r["text"]
            # 记录结构化产出，给后面的入库/校验插件用。
            # 并行分支要合并，不能只保留最后一个 dict（否则分类/抽取并行时下游会丢字段）。
            if isinstance(r.get("output"), dict):
                last_structured.update(r["output"])
            # 把这一步的产出摘要打出来，让人能"看到过程"
            if r.get("text"):
                preview = " ".join(r["text"].split())[:110]
                log("     ↳ %d 字：%s…" % (len(r["text"]), preview))
            emit(event="end", step=r["step"], name=r["name"], status=r["status"],
                 ms=r["ms"], error=r["error"])
            icon = "✅" if r["status"] == "ok" else "❌"
            log("  %s %s · %d ms" % (icon, r["name"], r["ms"]))
            if r["error"]:
                log("     出错：%s" % r["error"])

        # 失败就停：别拿失败步骤的输出往下走（否则脏数据会一路写进库里）
        if any(r["status"] == "failed" for r in results):
            stopped = True
            break

    # 上游失败了 → 把没跑的步骤也记下来，界面上才看得出"是没跑，不是过了"
    if stopped:
        done = {s["step"] for s in steps}
        for item in ordered:
            sid = item.get("step", "")
            if sid in done:
                continue
            rep = StepReport(
                step=sid,
                name=item.get("name", ""),
                kind=item.get("kind", ""),
                brief=item.get("brief", ""),
                note=item.get("note", ""),
            )
            rep["status"] = "skipped"
            rep["error"] = "上游步骤失败，已跳过"
            steps.append(rep)
            emit(event="end", step=sid, name=item.get("name", ""), status="skipped", ms=0,
                 error="上游步骤失败，已跳过")
            log("  ⏭ %s · 已跳过（上游失败）" % item.get("name", ""))

    ms = int((time.time() - started) * 1000)
    # degraded = "该做但没做"（主模型不可用），不算失败，但也不等于成功
    ok = all(s["status"] in ("ok", "degraded") for s in steps)
    log_event(
        "run_end",
        ok=ok,
        ms=ms,
        steps=len(steps),
        degraded=sum(1 for s in steps if s["status"] == "degraded"),
        failed=sum(1 for s in steps if s["status"] == "failed"),
        retried=sum(int(s.get("retries") or 0) for s in steps),
    )
    return {"ok": ok, "steps": steps, "ms": ms, "text": current_text}
