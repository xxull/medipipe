# -*- coding: utf-8 -*-
"""
页面 2：画布编排（page2_canvas）
=========================================================================
这个文件只做"页面组装"，具体实现都在 ui/canvas/ 下：

    state_画布状态.py   数据与逻辑（增删、连线、JSON、撤销）
    edit_画布编辑.py    编辑器控件（连线面板、节点/连线表单）
    view_画布视图.py    画布渲染 + 结果预览

页面顺序：
    ① 让主模型画图（有 Key 才显示）
    ② 扫描工具栏（重新扫描 / 选文件夹 / 全电脑扫描 / 扫描模型）
    ③ 新节点从哪来 + 添加
    ④ 工具栏（撤销 / 适应窗口 / 清空 / 导入导出）
    ⑤ 左：画布    右：串行并行说明
=========================================================================
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import streamlit as st

from core.loader_模块加载 import load as _load

_state = _load("ui/canvas/state_画布状态.py", "ui_canvas_state")
_view = _load("ui/canvas/view_画布视图.py", "ui_canvas_view")

# 兼容：外部/测试可能要拿清单
CATALOG_KEYS = _state.cat_keys()


# -------------------------------------------------------------------------
# 让主模型画图
# -------------------------------------------------------------------------
DRAW_SYSTEM = """你是数据流水线的架构师。用户会用一句话说他要做什么，
你要把它拆成"节点 + 连线"的流程图。

规则：
1. 只能从下面【可用类型】里选类型，不要自己编。
2. 串行就是 A→B→C 一条接一条；并行就是同一个节点分出多条线。
3. 每个节点给一句 brief（告诉执行者这一步具体做什么，可空）。
4. 每条线给一句 note（可空），说明为什么这样连。
5. 必须先抓取/读取数据，再做处理。
6. 只输出 JSON，不要解释，不要代码块标记。"""

DRAW_USER = """【可用类型】
{types}

【用户想做的事】
{goal}

【输出格式】
{{"plan": "一句话说明你的安排",
  "nodes": [{{"id": "n1", "name": "抓取", "type": "网页抓取", "brief": "抓取网页正文"}}],
  "edges": [{{"from": "n1", "to": "n2", "note": "抓完再分类"}}]}}
"""


def _layout(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> None:
    """按层级排版：左→右为深度，同层上→下。"""
    ids = [n["id"] for n in nodes]
    indeg = {i: 0 for i in ids}
    out = {i: [] for i in ids}
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a in out and b in indeg:
            out[a].append(b)
            indeg[b] += 1

    depth = {i: 0 for i in ids}
    changed, guard = True, 0
    while changed and guard < 50:
        changed, guard = False, guard + 1
        for a, bs in out.items():
            for b in bs:
                if depth[b] < depth[a] + 1:
                    depth[b] = depth[a] + 1
                    changed = True

    per: Dict[int, int] = {}
    for n in nodes:
        d = depth.get(n["id"], 0)
        k = per.get(d, 0)
        per[d] = k + 1
        n["pos"] = (70 + d * 230, 40 + k * 130)


def _ask_master_graph(goal: str, catalog: Dict[str, Dict[str, Any]], keys: List[str]):
    from core.llm_主模型 import LLMError, MasterLLM, parse_json_loose

    key = st.session_state.get("main_api_key") or ""
    if not key:
        return False, None, "没有主模型 Key"

    type_lines = []
    for k in keys:
        m = catalog.get(k, {})
        desc = m.get("desc") or ""
        type_lines.append("- %s（%s）%s" % (k, m.get("tag", ""), ("：" + desc) if desc else ""))
    user = DRAW_USER.format(types="\n".join(type_lines), goal=goal.strip())

    try:
        master = MasterLLM(
            key=key,
            base=st.session_state.get("main_base") or "https://api.deepseek.com",
            model=st.session_state.get("main_model") or "deepseek-chat",
            budget_cny=0.10,
            timeout=60,
        )
        raw = master.chat(DRAW_SYSTEM, user, max_tokens=900)
        data = parse_json_loose(raw)
        if not isinstance(data, dict) or "nodes" not in data:
            return False, None, "主模型返回的格式不对：%s" % str(raw)[:120]
        st.session_state["master_usage"] = master.usage.as_dict()
        return True, data, ""
    except LLMError as exc:
        return False, None, str(exc)
    except Exception as exc:
        return False, None, "调用失败：%s" % exc


def _apply_graph(data: Dict[str, Any], catalog: Dict[str, Dict[str, Any]], keys: List[str]) -> str:
    """把主模型给的图铺到画布上（校正类型、补默认值、自动排版）。"""
    raw_nodes = data.get("nodes") or []
    if not raw_nodes:
        return "主模型没给出任何节点"

    unknown = []

    def fix_type(t: str) -> str:
        t = str(t or "").strip()
        if t in catalog:
            return t
        for k in keys:
            if t and (t in k or k in t):
                return k
        unknown.append(t or "（空类型）")
        return ""

    nodes, id_map = [], {}
    for i, n in enumerate(raw_nodes, start=1):
        typ = fix_type(n.get("type"))
        if not typ:
            continue
        nid = "m%d" % i
        id_map[str(n.get("id") or i)] = nid
        nodes.append({
            "id": nid,
            "label": str(n.get("name") or "").strip()[:12],
            "choice": typ,
            "name_mode": _state.NAME_SELF if n.get("name") else _state.NAME_AUTO,
            "brief": str(n.get("brief") or "")[:200],
            "pos": (80, 40),
        })

    if unknown:
        return "主模型给了不存在的类型：%s。请先重新扫描插件，或手动添加节点。" % "、".join(sorted(set(unknown)))
    if not nodes:
        return "主模型没有给出可用节点"

    edges = []
    for i, e in enumerate(data.get("edges") or [], start=1):
        a = id_map.get(str(e.get("from") or e.get("source") or e.get("src") or ""))
        b = id_map.get(str(e.get("to") or e.get("target") or e.get("dst") or ""))
        if not a or not b or a == b:
            continue
        edges.append({"id": "me%d" % i, "source": a, "target": b, "note": str(e.get("note") or "")[:100]})

    _layout(nodes, edges)
    _state.snapshot()

    st.session_state["flow_nodes"] = nodes
    st.session_state["flow_edges"] = edges
    st.session_state["node_seq"] = len(nodes)
    st.session_state["edge_seq"] = len(edges)
    st.session_state["flow_state"] = None
    st.session_state["built_ver"] = -1
    st.session_state["need_fit"] = True
    st.session_state["edit_node"] = ""
    st.session_state["edit_edge"] = ""
    _state.bump()
    return ""


def _master_draw_block(catalog: Dict[str, Dict[str, Any]], keys: List[str]) -> None:
    has_key = bool(st.session_state.get("main_api_key"))
    with st.container(border=True):
        st.markdown("**🤖 让主模型帮我画图**")
        if not has_key:
            st.caption("需要先在「选项 1」里填好主模型的 API Key。没 Key 也能手动加节点、连线条。")
            return

        goal = st.text_area(
            "我想要…（一句话说清目标，节点和连线让主模型安排）",
            height=70,
            placeholder="例如：抓取这几个网页，先压缩再抽取字段，最后让主模型检查一下",
            key="master_goal",
        )
        c1, c2 = st.columns([1, 4])
        with c1:
            go = st.button("让主模型画图", type="primary", width="stretch")
        with c2:
            st.caption("主模型只负责画路线，具体执行还是靠你选好的插件和模型；画完可以自己改。")

        if go:
            if not goal.strip():
                st.warning("先写一句你想做什么")
            else:
                with st.spinner("主模型正在拆解任务、安排连线…"):
                    ok, data, err = _ask_master_graph(goal, catalog, keys)
                if not ok:
                    st.error(err)
                else:
                    err2 = _apply_graph(data, catalog, keys)
                    if err2:
                        st.error(err2)
                    else:
                        st.session_state["master_plan"] = data.get("plan", "")
                        usage = st.session_state.get("master_usage") or {}
                        st.success("画好了：%d 个节点、%d 条线（花了 %.4f 元）"
                                   % (len(data.get("nodes") or []), len(data.get("edges") or []),
                                      usage.get("cost_cny", 0)))
                        st.rerun()

        if st.session_state.get("master_plan"):
            st.info("主模型的安排：" + st.session_state["master_plan"])


# -------------------------------------------------------------------------
# 工具栏
# -------------------------------------------------------------------------
def _scan_toolbar(catalog: Dict[str, Dict[str, Any]]) -> None:
    s1, s2, s3, s4, s5 = st.columns([1.1, 1.1, 1.3, 1.1, 2])
    with s1:
        if st.button("↻ 重新扫描插件", width="stretch"):
            _state.rescan()
            st.rerun()
    with s2:
        if st.button("🔎 扫描本地模型", width="stretch"):
            with st.spinner("正在扫模型…"):
                _state.rescan(with_models=True, deep=True)
            n = sum(1 for m in _state.catalog().values() if m.get("kind") == "model")
            st.success("扫到 %d 个模型" % n) if n else st.info("没扫到模型")
            st.rerun()
    with s3:
        if st.button("📁 从我的电脑里选择", width="stretch"):
            from core.picker_本机选择 import pick_folder

            picked = pick_folder("选择插件所在的文件夹")
            if picked:
                if picked not in st.session_state["extra_dirs"]:
                    st.session_state["extra_dirs"].append(picked)
                _state.rescan()
                st.success("已加入：%s" % picked)
                st.rerun()
            else:
                st.info("没选文件夹（或弹不出对话框），可以在下面手动粘路径")
    with s4:
        if st.button("🌐 全电脑扫描", width="stretch"):
            with st.spinner("正在扫全盘，最多 25 秒…"):
                result = _state._scanner.scan_full_disk(max_seconds=25, max_files=3000, max_depth=5)
            st.session_state["disk_plugins"] = result["found"]
            st.session_state["disk_stats"] = result
            _state.rescan()
            st.rerun()
    with s5:
        st.markdown(
            '<span title="本扫描结果是根据扫描所认定的插件所得出的结果，可能会扫描不全。">'
            "⚠️ 全电脑扫描只认「继承 BasePlugin 的类」，有时间和文件数上限，会跳过系统目录，"
            "所以**一定扫不全**。</span>",
            unsafe_allow_html=True,
        )

    stats = st.session_state.get("disk_stats")
    if stats:
        st.caption("上次全盘扫描：检查 %d 个 .py，找到 %d 个插件，用时 %s 秒%s"
                   % (stats.get("checked", 0), len(stats.get("found", [])), stats.get("seconds", 0),
                      "（到上限提前停了，可能不全）" if stats.get("truncated") else ""))

    with st.expander("手动加一个文件夹", expanded=False):
        new_dir = st.text_input("文件夹路径", placeholder="D:\\我的代码", label_visibility="collapsed")
        if st.button("加入扫描", key="add_dir") and new_dir:
            if new_dir not in st.session_state["extra_dirs"]:
                st.session_state["extra_dirs"].append(new_dir)
            _state.rescan()
            st.rerun()
        if st.session_state["extra_dirs"]:
            st.caption("已加入：" + "、".join(st.session_state["extra_dirs"]))

    kinds: Dict[str, int] = {}
    for m in catalog.values():
        kinds[m.get("tag", "?")] = kinds.get(m.get("tag", "?"), 0) + 1
    st.caption("可用：" + "、".join("%s %d" % (k, v) for k, v in kinds.items()))


def _import_export() -> None:
    """工作流导出/导入（画布不再"关掉就没"）。"""
    workflow = st.session_state.get("workflow") or []
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "⬇️ 导出工作流",
            data=json.dumps(workflow, ensure_ascii=False, indent=2),
            file_name="workflow.json",
            mime="application/json",
            width="stretch",
            disabled=not workflow,
        )
    with c2:
        up = st.file_uploader("⬆️ 导入工作流", type=["json"], label_visibility="collapsed")
        if up is not None:
            try:
                data = json.loads(up.read().decode("utf-8"))
            except Exception as exc:
                st.error("这个文件不是合法 JSON：%s" % exc)
                return
            if not isinstance(data, list) or not data:
                st.error("文件里应该是一个步骤列表")
                return
            _state.snapshot()
            st.session_state["flow_nodes"] = [
                {
                    "id": "i%d" % i,
                    "label": w.get("name") or w.get("step", ""),
                    "choice": next((k for k in _state.cat_keys()
                                    if _state.meta(k).get("key") == w.get("step")), None)
                              or (w.get("tag") or "").strip() or _state.cat_keys()[0],
                    "name_mode": _state.NAME_SELF,
                    "brief": w.get("brief", ""),
                    "pos": (80 + (i % 3) * 200, 40 + (i // 3) * 120),
                }
                for i, w in enumerate(data, start=0)
            ]
            st.session_state["flow_edges"] = []
            st.session_state["flow_state"] = None
            st.session_state["built_ver"] = -1
            st.session_state["need_fit"] = True
            _state.bump()
            st.success("导入 %d 个节点（连线需要重新连）" % len(data))
            st.rerun()


def render() -> None:
    st.subheader("② 画布编排")
    _state.init()
    catalog = _state.catalog()
    keys = _state.cat_keys()

    # ① 主模型画图
    _master_draw_block(catalog, keys)

    # ② 扫描
    _scan_toolbar(catalog)

    # ③ 新节点
    c1, c2 = st.columns([2, 3])
    with c1:
        default_idx = next((i for i, k in enumerate(keys) if catalog.get(k, {}).get("kind") == "plugin"), 0)
        pick = st.selectbox("新节点用什么", keys, index=default_idx, key="add_choice",
                            format_func=lambda k: "%s（%s）" % (k, catalog.get(k, {}).get("tag", "")))
    with c2:
        st.caption("")
        if st.button("＋ 添加这个节点", type="primary"):
            _state.snapshot()
            _state.add_node(pick)
            st.rerun()

    st.caption("「＋ 添加节点」→ 选类型自动起名（也可用原名 / 自己起 / 主模型起）→ 「连一条线」连起来 → 写备注。")

    # ④ 工具栏：撤销 / 适应窗口 / 清空 / 导入导出
    t1, t2, t3, t4 = st.columns([1, 1, 1, 2.6])
    with t1:
        if st.button("↶ 撤销", width="stretch"):
            if _state.undo():
                st.rerun()
            else:
                st.info("没有可撤销的操作")
    with t2:
        if st.button("🔍 适应窗口", width="stretch"):
            st.session_state["flow_state"] = None
            st.session_state["built_ver"] = -1
            st.session_state["need_fit"] = True
            _state.bump()
            st.rerun()
    with t3:
        if st.button("× 清空", width="stretch"):
            _state.snapshot()
            _state.clear()
            st.rerun()
    with t4:
        st.caption("节点 %d 个 · 连线 %d 条"
                   % (len(st.session_state["flow_nodes"]), len(st.session_state["flow_edges"])))

    with st.expander("导入 / 导出工作流", expanded=False):
        _import_export()

    # ⑤ 画布 + 说明
    col_canvas, col_help = st.columns([2.6, 1])
    with col_canvas:
        if not st.session_state["flow_nodes"]:
            st.info("画布是空的。上面选一个类型，点「＋ 添加这个节点」。")
        _view.canvas_area()

    with col_help:
        with st.expander("❓ 串行 / 并行 怎么画", expanded=True):
            st.caption("**箭头方向 = 执行方向**")
            st.markdown(
                ARROW_DEF + SVG_SERIAL,
                unsafe_allow_html=True,
            )
            st.markdown("**串行**：一条接一条。")
            st.markdown(SVG_PARALLEL, unsafe_allow_html=True)
            st.markdown("**并行**：从同一个节点拉出两条线。")
            st.divider()
            st.markdown("连不上就用上面的「连一条线」，选两个节点点一下，100% 成功。")


# -------------------------------------------------------------------------
# 说明用的小图
# -------------------------------------------------------------------------
ARROW_DEF = """<svg width="0" height="0"><defs>
  <marker id="ar" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
    <path d="M0,0 L6,3 L0,6 z" fill="#5b8cff"/>
  </marker></defs></svg>"""

SVG_SERIAL = """<svg viewBox="0 0 150 120" width="100%">
  <g font-size="9" text-anchor="middle" font-family="sans-serif">
    <rect x="35" y="4" width="80" height="22" rx="4" fill="#1b2947" stroke="#5b8cff"/>
    <text x="75" y="19" fill="#dbe3ff">A 抓取</text>
    <rect x="35" y="48" width="80" height="22" rx="4" fill="#1b2947" stroke="#5b8cff"/>
    <text x="75" y="63" fill="#dbe3ff">B 压缩</text>
    <rect x="35" y="92" width="80" height="22" rx="4" fill="#1b2947" stroke="#5b8cff"/>
    <text x="75" y="107" fill="#dbe3ff">C 分类</text>
    <line x1="75" y1="26" x2="75" y2="48" stroke="#5b8cff" marker-end="url(#ar)"/>
    <line x1="75" y1="70" x2="75" y2="92" stroke="#5b8cff" marker-end="url(#ar)"/>
  </g>
</svg>"""

SVG_PARALLEL = """<svg viewBox="0 0 150 120" width="100%">
  <g font-size="9" text-anchor="middle" font-family="sans-serif">
    <rect x="35" y="4" width="80" height="22" rx="4" fill="#1b2947" stroke="#5b8cff"/>
    <text x="75" y="19" fill="#dbe3ff">A 抓取</text>
    <rect x="2" y="84" width="66" height="22" rx="4" fill="#1b2947" stroke="#3fb950"/>
    <text x="35" y="99" fill="#dbe3ff">B 分类</text>
    <rect x="82" y="84" width="66" height="22" rx="4" fill="#1b2947" stroke="#3fb950"/>
    <text x="115" y="99" fill="#dbe3ff">C 压缩</text>
    <line x1="60" y1="26" x2="35" y2="84" stroke="#3fb950" marker-end="url(#ar)"/>
    <line x1="90" y1="26" x2="115" y2="84" stroke="#3fb950" marker-end="url(#ar)"/>
  </g>
</svg>"""
