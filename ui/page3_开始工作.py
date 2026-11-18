# -*- coding: utf-8 -*-
"""
页面 3：开始工作（page3_run）
=========================================================================
对应你设计的「选项 3」。

流程：
    ① 放数据（单条，或批量：一行一条）
    ② 看一眼要执行的步骤
    ③ 点「开始工作」→ 主模型先给一句话 → 按画布顺序真跑 → 实时滚日志 + 状态灯
    ④ 看结果：单条看细节；批量出表格，可下载 CSV

状态灯
-------------------------------------------------------------------------
    白 = 还没跑  黄 = 正在跑  绿 = 完成  红 = 失败
失败时会解释：本地翻译成人话；配了 Key 再让主模型给修法。

批量是什么意思
-------------------------------------------------------------------------
同一张流水线，喂多条输入（多个网址、多段文本），
每条跑一遍，结果一行一行攒成表格 —— 这就是"批量跑"。
=========================================================================
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import streamlit as st

from core.loader_模块加载 import load as _load

_engine = _load("core/engine_执行引擎.py", "core_engine")
_loader = _load("core/plugins_加载实例.py", "core_plugin_loader")
_launcher = _load("core/launcher_服务启动.py", "core_launcher")
_scanner = _load("core/scanner_插件扫描.py", "core_scanner")
_errors = _load("core/errors_报错翻译.py", "core_errors")

try:
    from config_配置 import MAX_BATCH
except Exception:
    MAX_BATCH = 50


def _catalog() -> Dict[str, Dict[str, Any]]:
    """复用选项 2 扫出来的清单；没扫过就现扫一次。"""
    if not st.session_state.get("catalog"):
        st.session_state["catalog"] = _scanner.build_catalog(
            extra_dirs=st.session_state.get("extra_dirs") or [],
            with_models=True,
            extra_plugins=st.session_state.get("disk_plugins") or [],
        )
    return st.session_state["catalog"]


def _make_master():
    """按选项 1 配好的 Key 建主模型客户端。"""
    from core.llm_主模型 import MasterLLM

    key = st.session_state.get("main_api_key") or ""
    if not key:
        return None
    return MasterLLM(
        key=key,
        base=st.session_state.get("main_base") or "https://api.deepseek.com",
        model=st.session_state.get("main_model") or "deepseek-chat",
        budget_cny=0.5,
        timeout=60,
    )


def _supervise(master, workflow: List[Dict[str, Any]], has_input: bool) -> str:
    """开始前的"主模型说一句话"；画图时已生成过计划就直接复用（省钱）。"""
    if master is None:
        return "本地模式：按画布顺序执行"

    cached = st.session_state.get("master_plan")
    if cached:
        return "（沿用画图时的安排）" + cached

    lines = ["- %s（%s）%s" % (w.get("name"), w.get("tag") or w.get("kind"), w.get("brief") or "")
             for w in workflow]
    try:
        return master.chat(
            "你是流水线主管。用一句话确认你理解了这串步骤，不要解释、不要列清单。",
            "要执行的步骤：\n%s\n\n有没有输入数据：%s" % ("\n".join(lines), "有" if has_input else "没有"),
            max_tokens=120,
        ).strip()
    except Exception as exc:
        return "主模型不在线（%s），直接按顺序执行" % exc


COLORS = {
    "pending": ("#8b949e", "#161b22", "还没跑"),
    "running": ("#d29922", "#2a2013", "正在跑…"),
    "ok": ("#3fb950", "#12261a", "完成"),
    "failed": ("#f85149", "#2a1518", "失败"),
    # 降级：该做但没做（比如没配主模型），不算失败，用琥珀色
    "degraded": ("#d29922", "#2a2013", "已降级"),
}


def _board_html(states: Dict[str, Dict[str, Any]]) -> str:
    """把每一步画成一张小卡片，按状态上色。"""
    cards = []
    for _key, info in sorted(states.items(), key=lambda kv: kv[1]["order"]):
        border, bg, word = COLORS.get(info["status"], COLORS["pending"])
        tail = ("· %d ms" % info["ms"]) if info["status"] in ("ok", "failed") else ""
        cards.append(
            '<div style="display:inline-block;min-width:150px;margin:4px;padding:10px 12px;'
            "border:2px solid %s;border-radius:8px;background:%s;color:#e6edf3;"
            'font-size:13px;line-height:1.5;">'
            '<b>%d. %s</b><br><span style="color:%s">%s %s</span></div>'
            % (border, bg, info["order"], info["name"], border, word, tail)
        )
    return "".join(cards)


def _collect_fields(report: Dict[str, Any], limit: int = 8) -> Dict[str, Any]:
    """
    从各步骤的产出里**动态**收集字段，拼成表格的列。

    框架不知道具体业务，所以不做任何字段假设：
        * 插件返回 dict → 把它的键值对摊平进来
        * 值是列表 → 用"、"连起来
        * 值是字符串 → 原样（截断）
    列数上限 limit，避免某个插件返回几十个字段把表格撑爆。
    """
    out: Dict[str, Any] = {}
    for s in report.get("steps", []):
        payload = s.get("output")
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if len(out) >= limit:
                return out
            if key in ("text", "output", "content", "result", "method", "paid"):
                continue          # 这些是内部字段，不进表
            if isinstance(value, (list, tuple)):
                out[key] = "、".join(str(v) for v in value)[:80]
            elif isinstance(value, (str, int, float, bool)):
                text = str(value)
                out[key] = text[:80]
    return out


LINK_SYSTEM = """你熟悉公开数据源的分布。用户要找某类原始资料，你列出**最可能有原文的入口**。

规则：
1. 优先给**官方/权威**站点（政府、交易所、机构官网、开放获取期刊库）。
2. 每条给：标题、完整 URL、一句话说明"这里有什么"。
3. 只输出 JSON，不要解释，格式：
   {"links": [{"title": "…", "url": "https://…", "why": "…"}]}
4. 最多 5 条；不确定的宁可不给，不要编造。"""


def _ask_master_links(goal: str) -> tuple:
    """让主模型给几个可能的数据源链接。返回 (成功?, 列表或错误)。"""
    from core.llm_主模型 import MasterLLM, LLMError, parse_json_loose

    key = st.session_state.get("main_api_key") or ""
    if not key:
        return False, "先在「选项 1」配好主模型 Key"

    try:
        master = MasterLLM(
            key=key,
            base=st.session_state.get("main_base") or "https://api.deepseek.com",
            model=st.session_state.get("main_model") or "deepseek-chat",
            budget_cny=0.05,
            timeout=45,
        )
        raw = master.chat(LINK_SYSTEM, "我要找：%s" % goal.strip(), max_tokens=600)
        data = parse_json_loose(raw)
        links = data.get("links") if isinstance(data, dict) else None
        if not isinstance(links, list) or not links:
            return False, "主模型没给出可用的链接，换个说法再试"
        clean = []
        for item in links[:5]:
            url = str(item.get("url") or "").strip()
            if not url.startswith("http"):
                continue
            clean.append({
                "title": str(item.get("title") or "")[:60],
                "url": url[:300],
                "why": str(item.get("why") or "")[:80],
            })
        if not clean:
            return False, "主模型给的链接格式不对"
        return True, clean
    except LLMError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, "调用失败：%s" % exc


def _source_helper() -> None:
    """「不知道去哪找」小工具：主模型给链接，点一下填进输入框。"""
    has_key = bool(st.session_state.get("main_api_key"))

    with st.expander("🔎 不知道去哪儿找？让主模型给几个链接", expanded=False):
        if not has_key:
            st.caption("需要先在「选项 1」填主模型 Key。")
            return

        st.caption("说清你要什么（公司+年份+报告类型、或某个主题），主模型会给出可能的官方入口。")
        c1, c2 = st.columns([3, 1])
        with c1:
            goal = st.text_input(
                "我要找",
                value=st.session_state.get("find_goal", ""),
                placeholder="例如：贵州茅台 2023 年年度报告",
                label_visibility="collapsed",
            )
            st.session_state["find_goal"] = goal
        with c2:
            if st.button("帮我找", key="find_links", width="stretch"):
                if not goal.strip():
                    st.warning("先写一句你要找什么")
                else:
                    with st.spinner("主模型正在想…"):
                        ok, result = _ask_master_links(goal)
                    if ok:
                        st.session_state["found_links"] = result
                    else:
                        st.error(result)

        for item in st.session_state.get("found_links") or []:
            lc1, lc2 = st.columns([4, 1])
            with lc1:
                st.markdown("**%s**" % (item["title"] or item["url"]))
                st.caption(item["url"])
                if item.get("why"):
                    st.caption("· " + item["why"])
            with lc2:
                if st.button("用这个", key="use_" + item["url"], width="stretch"):
                    st.session_state["_prefill_text"] = item["url"]
                    st.rerun()

        if st.session_state.get("found_links"):
            st.warning("⚠️ 链接是主模型凭记忆给的，**可能不准**。用之前先点开确认一下。")


def render() -> None:
    st.subheader("③ 开始工作")

    workflow = st.session_state.get("workflow") or []

    # ---------- 输入 ----------
    st.markdown("**① 放数据**")
    mode = st.radio("跑几条", ["单条", "批量（一行一条）"], horizontal=True, key="run_mode")

    # 找不到数据源时，让主模型给几个链接（通用能力，不限于某个行业）
    _source_helper()

    if mode == "单条":
        raw = st.text_area(
            "粘贴文本，或者直接粘一个网址",
            height=150,
            placeholder="把要处理的文本贴进来；也可以直接粘 https://… 的网址，会自动抓正文",
            key="run_text",
        )
        items = [raw.strip()] if raw and raw.strip() else []
        if items:
            st.caption("🔗 识别为网址" if re.match(r"^https?://\S+$", items[0]) else "📄 识别为文本：%d 字" % len(items[0]))
        else:
            st.caption("还没放数据")
    else:
        bulk = st.text_area(
            "一行一条（网址或文本都行）",
            height=180,
            placeholder="https://example.com/a\nhttps://example.com/b\n或者直接一段要处理的文本…",
            key="run_bulk",
        )
        lines = [x.strip() for x in (bulk or "").splitlines() if x.strip()]
        items = lines[:MAX_BATCH]
        st.caption("识别到 **%d** 条%s" % (len(items), ("（只跑前 %d 条）" % MAX_BATCH) if len(lines) > MAX_BATCH else ""))
        if items:
            with st.expander("看看这 %d 条" % len(items)):
                for i, x in enumerate(items, start=1):
                    st.caption("%d. %s" % (i, x[:90]))

    # ---------- 步骤概览 ----------
    st.markdown("**② 要执行的步骤**")
    if not workflow:
        st.info("画布还是空的，先去「选项 2」画一张图。")
        return
    if st.session_state.get("workflow_errors"):
        st.error("流程有错误，已阻止执行：\n" + "\n".join(st.session_state["workflow_errors"]))
        return

    for w in workflow:
        mark = "∥" if w.get("parallel_group") else "↓"
        st.caption("%s %d. %s（%s）%s" % (
            mark, w.get("order", 0), w.get("name"), w.get("tag") or w.get("kind"),
            (" — " + w["brief"]) if w.get("brief") else "",
        ))

    has_master_node = any(w.get("kind") == "master" for w in workflow)
    has_model_node = any(w.get("kind") == "model" for w in workflow)
    has_key = bool(st.session_state.get("main_api_key"))

    if has_master_node and not has_key:
        st.warning("图里有主模型节点，但选项 1 还没填 Key —— 跑到那一步会失败。")
    if has_model_node:
        st.caption("图里有本地模型节点，执行前会自动检查 Ollama。")

    # 每步超时：默认取配置，急的时候可以调小
    try:
        from config_配置 import STEP_TIMEOUT as _DEFAULT_TIMEOUT
    except Exception:
        _DEFAULT_TIMEOUT = 180.0
    _c1, _c2 = st.columns(2)
    with _c1:
        step_timeout = st.number_input(
            "每步超时（秒）", min_value=5, max_value=1800,
            value=int(_DEFAULT_TIMEOUT), step=5,
            help="单步超过这个时间就判失败并跳过，防止插件卡死拖住整条流水线",
        )
    with _c2:
        retry_max = st.number_input(
            "失败重试次数", min_value=0, max_value=3, value=0, step=1,
            help="只对「重跑可能有用」的错误重试（网络/超时/限流/JSON 坏）；"
                 "缺插件、文件不存在这类直接失败，不浪费时间和钱",
        )

    # ---------- 开始 ----------
    st.divider()
    c1, c2 = st.columns([1, 3])
    with c1:
        go = st.button("▶️ 开始工作", type="primary", width="stretch",
                       disabled=not (workflow and items))
    with c2:
        if not items:
            st.caption("先在上面放点数据")

    if go:
        master = _make_master()

        # 状态灯
        states: Dict[str, Dict[str, Any]] = {}
        for w in workflow:
            states[w.get("step", "")] = {
                "name": w.get("name", ""),
                "order": w.get("order", 0),
                "status": "pending",
                "ms": 0,
                "error": "",
            }
        board = st.empty()
        board.markdown(_board_html(states), unsafe_allow_html=True)

        status = st.status("准备中…", expanded=(len(items) == 1))

        def log(msg: str) -> None:
            status.write(msg)

        def on_event(ev: Dict[str, Any]) -> None:
            key = ev.get("step", "")
            if key not in states:
                return
            if ev.get("event") == "start":
                states[key]["status"] = "running"
            elif ev.get("event") == "end":
                states[key]["status"] = ev.get("status", "failed")
                states[key]["ms"] = ev.get("ms", 0)
                states[key]["error"] = ev.get("error", "")
            board.markdown(_board_html(states), unsafe_allow_html=True)

        # 1) 探活
        if has_model_node:
            log("检查 Ollama…")
            ok_srv, msg = _launcher.ensure_ollama(True)
            log(("  ✅ " if ok_srv else "  ⚠️ ") + msg)

        # 2) 主管说一句（批量也只说一次，省钱）
        feedback = _supervise(master, workflow, bool(items))
        log("🧭 主管：" + feedback)

        # 3) 加载插件
        plugin_files = {(w.get("key") or w["step"]): w.get("file", "") for w in workflow
                        if w.get("kind") == "plugin" and w.get("file")}
        log("加载插件：%d 个" % len(plugin_files))
        instances = _loader.load_instances(plugin_files)
        missing = [k for k in plugin_files if k not in instances]
        if missing:
            log("  ⚠️ 没加载上：%s" % "、".join(missing))
            errors = getattr(_loader, "LAST_ERRORS", {})
            for key in missing:
                if key in errors:
                    log("     %s：%s" % (key, errors[key]))

        # 4) 跑（单条 = 1 次，批量 = N 次）
        status.update(label=("执行中…" if len(items) == 1 else "批量执行中（1/%d）…" % len(items)),
                      state="running")
        if len(items) > 1:
            progress = st.progress(0.0, text="0 / %d" % len(items))

        runs: List[Dict[str, Any]] = []
        for idx, item in enumerate(items, start=1):
            # 每条开始前把灯复位（多跑几条时能看出"这一条"的状态）
            for info in states.values():
                info["status"] = "pending"
                info["ms"] = 0
                info["error"] = ""
            board.markdown(_board_html(states), unsafe_allow_html=True)

            if len(items) > 1:
                status.update(label="批量执行中（%d/%d）…" % (idx, len(items)), state="running")
                log("—— 第 %d/%d 条：%s" % (idx, len(items), item[:60]))

            report = _engine.run_workflow(
                workflow, plugins=instances, master=master, input_text=item,
                logger=log if len(items) == 1 else None, on_event=on_event,
                step_timeout=float(step_timeout),
                retry_max=int(retry_max),
            )
            runs.append({"item": item, "report": report})

            if len(items) > 1:
                progress.progress(idx / len(items), text="%d / %d" % (idx, len(items)))

        # 5) 失败解释（每条最多解释第一次失败）
        explain_list: List[Dict[str, str]] = []
        for r in runs:
            failed = next((s for s in r["report"]["steps"] if s["status"] == "failed"), None)
            if not failed:
                continue
            item = {
                "input": r["item"][:60],
                "step": failed["name"],
                "error": failed.get("error", ""),
                "local": _errors.explain_local(failed.get("error", "")),
                "master": "",
            }
            if master is not None:
                ok_m, text = _errors.explain_with_master(
                    master, failed.get("name", ""), failed.get("brief", ""), failed.get("error", "")
                )
                if ok_m:
                    item["master"] = text
            explain_list.append(item)

        usage = master.usage.as_dict() if master else {"calls": 0, "cost_cny": 0.0}
        ok_all = all(r["report"]["ok"] for r in runs)
        status.update(
            label=("全部完成 ✅" if ok_all else "有失败 ❌") + "（%d 条）" % len(runs),
            state="complete" if ok_all else "error",
        )
        # 存进 session 之前，把长文本截断：批量跑几十条时避免内存越滚越大
        for r in runs:
            for s in r["report"].get("steps", []):
                if isinstance(s.get("text"), str) and len(s["text"]) > 3000:
                    s["text"] = s["text"][:3000] + "…（截断）"
            if isinstance(r["report"].get("text"), str) and len(r["report"]["text"]) > 3000:
                r["report"]["text"] = r["report"]["text"][:3000] + "…（截断）"

        st.session_state["run_report"] = {
            "runs": runs,
            "usage": usage,
            "feedback": feedback,
            "explain": explain_list,
            "batch": len(items) > 1,
        }

    # ---------- 结果 ----------
    saved = st.session_state.get("run_report")
    if not saved:
        return

    runs = saved["runs"]
    usage = saved["usage"]
    explain_list = saved.get("explain") or []

    st.divider()
    st.markdown("**③ 结果**")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("跑了", "%d 条" % len(runs))
    ok_count = sum(1 for r in runs if r["report"]["ok"])
    degraded_count = sum(
        1 for r in runs for s in r["report"].get("steps", []) if s.get("status") == "degraded"
    )
    m2.metric("成功", "%d 条" % ok_count)
    m3.metric("主模型花费", "%.4f 元" % usage.get("cost_cny", 0))
    m4.metric("结论", "全部通过" if ok_count == len(runs) else "%d 条失败" % (len(runs) - ok_count))

    if degraded_count:
        st.caption("其中 %d 步是「降级」：主模型不可用，这一步该做但没做（不算失败）" % degraded_count)

    st.caption("主管意见：" + saved.get("feedback", ""))

    for e in explain_list:
        st.error("**%s 失败**（%s）：%s%s" % (
            e["step"], e["input"], e["local"],
            ("\n\n🧭 主模型： " + e["master"]) if e["master"] else "",
        ))

    if saved.get("batch"):
        # 批量：出表格
        rows = []
        for i, r in enumerate(runs, start=1):
            rep = r["report"]
            paid = any(
                isinstance(s.get("output"), dict) and s["output"].get("paid")
                for s in rep.get("steps", [])
            )
            row = {
                "序号": i,
                "输入": r["item"][:50],
                "状态": "成功" if rep["ok"] else "失败",
                "耗时ms": rep["ms"],
                "花钱": "是" if paid else "",
            }
            row.update(_collect_fields(rep))
            rows.append(row)

        st.dataframe(rows, width="stretch", hide_index=True)

        # 下载
        import csv
        import io

        buf = io.StringIO()
        # 每条结果的动态字段可能不同；用并集，避免后面的行出现新字段时 DictWriter 抛异常。
        fields = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        st.download_button("⬇️ 下载 CSV", data=buf.getvalue().encode("utf-8-sig"),
                           file_name="批量结果.csv", mime="text/csv")

        with st.expander("每条的详细产出"):
            for i, r in enumerate(runs, start=1):
                st.markdown("**%d. %s**" % (i, r["item"][:60]))
                for s in r["report"]["steps"]:
                    st.caption("%s %s · %d ms" % ("✅" if s["status"] == "ok" else "❌", s["name"], s["ms"]))
                if r["report"]["text"]:
                    st.text(r["report"]["text"][:400])
    else:
        # 单条：详细展示
        rep = runs[0]["report"]
        for s in rep["steps"]:
            icon = "✅" if s["status"] == "ok" else "❌"
            with st.expander("%s %s · %d ms%s" % (
                icon, s["name"], s["ms"], (" · " + s["brief"]) if s.get("brief") else ""),
                expanded=(s["status"] != "ok"),
            ):
                if s["error"]:
                    st.error(s["error"])
                if isinstance(s["output"], (dict, list)):
                    st.json(s["output"], expanded=True)
                elif s.get("text"):
                    st.text(s["text"][:2000])

        # 结构化产出：取**最后一个**返回 dict 的步骤（框架不假设字段名）
        structured = None
        for s in rep["steps"]:
            if isinstance(s.get("output"), dict):
                structured = s["output"]
        if structured:
            st.markdown("**结构化产出**")
            st.json(structured, expanded=True)
            st.download_button(
                "⬇️ 下载 JSON",
                data=json.dumps(structured, ensure_ascii=False, indent=2),
                file_name="output.json",
                mime="application/json",
            )

    # 运行日志（落盘在 data/app.log，关掉页面也能查）
    with st.expander("运行日志（data/app.log）", expanded=False):
        try:
            from core.log_日志 import LOG_PATH, tail

            st.caption("文件：%s" % LOG_PATH)
            st.code(tail(60), language="json")
        except Exception as exc:
            st.caption("读日志失败：%s" % exc)

    with st.expander("完整报告（给框架二用）"):
        st.json({"runs": [r["report"] for r in runs], "usage": usage}, expanded=False)
