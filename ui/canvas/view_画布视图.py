# -*- coding: utf-8 -*-
"""
画布视图（canvas view）
=========================================================================
管三件事：
    * 画布本体（streamlit_flow，包在 fragment 里防闪）
    * 节点/连线选择器
    * 底部"执行 JSON"预览（步骤数、串并行、可折叠全文）

编辑器控件在 edit_画布编辑.py，数据逻辑在 state_画布状态.py。
=========================================================================
"""

from __future__ import annotations

import streamlit as st

from core.loader_模块加载 import load as _load

_state = _load("ui/canvas/state_画布状态.py", "ui_canvas_state")
_edit = _load("ui/canvas/edit_画布编辑.py", "ui_canvas_edit")

try:
    from streamlit_flow import streamlit_flow

    FLOW_OK = True
    FLOW_ERR = ""
except Exception as _exc:  # pragma: no cover
    FLOW_OK = False
    FLOW_ERR = str(_exc)


@st.fragment
def canvas_area() -> None:
    """画布 + 编辑器 + JSON（fragment：拖动只刷这一块）。"""
    if not FLOW_OK:
        st.error("画布组件没装好：%s\n\n请运行：pip install streamlit-flow-component" % FLOW_ERR)
        return

    nodes = st.session_state["flow_nodes"]
    edges = st.session_state["flow_edges"]

    # 连一条线（不依赖拖拽，100% 成功）
    _edit.connect_panel()

    # 选节点 / 选连线
    if nodes:
        c1, c2 = st.columns(2)
        with c1:
            opts = ["（不编辑）"] + [
                "%s（%s）［%s］" % (n.get("label") or "未命名",
                                   _state.meta(n["choice"]).get("tag", ""), n["id"])
                for n in nodes
            ]
            ids = [""] + [n["id"] for n in nodes]
            cur = ids.index(st.session_state["edit_node"]) if st.session_state.get("edit_node") in ids else 0
            pick = st.selectbox("选节点", opts, index=cur)
            sel_node = ids[opts.index(pick)]
            st.session_state["edit_node"] = sel_node
        with c2:
            names = {n["id"]: (n.get("label") or "未命名") for n in nodes}
            eopts = ["（不编辑）"] + [
                "%s → %s ［%s］" % (names.get(e["source"], e["source"]),
                                   names.get(e["target"], e["target"]), e["id"])
                for e in edges
            ]
            eids = [""] + [e["id"] for e in edges]
            ecur = eids.index(st.session_state["edit_edge"]) if st.session_state.get("edit_edge") in eids else 0
            epick = st.selectbox("选连线", eopts, index=ecur)
            sel_edge = eids[eopts.index(epick)]
            st.session_state["edit_edge"] = sel_edge

        if sel_node:
            _edit.node_form(sel_node)
        if sel_edge:
            _edit.edge_form(sel_edge)

    # 画布本体
    if st.session_state["flow_state"] is None or st.session_state["built_ver"] != st.session_state["graph_ver"]:
        st.session_state["flow_state"] = _state.build_state()
        st.session_state["built_ver"] = st.session_state["graph_ver"]

    # 放大连接点：默认的圆点只有 6px，鼠标很难点中。
    # 组件不提供参数，只能注入 CSS 改那个伪元素。
    st.markdown(
        "<style>"
        ".react-flow__handle{width:14px;height:14px;border:2px solid #58a6ff;"
        "background:#0d1117;}"
        ".react-flow__handle:hover{background:#58a6ff;transform:scale(1.25);}"
        ".react-flow__handle-left,.react-flow__handle-right{top:50%;}"
        "</style>",
        unsafe_allow_html=True,
    )

    new_state = streamlit_flow(
        "flow_canvas",
        st.session_state["flow_state"],
        height=380,
        fit_view=st.session_state["need_fit"],
        # 组件自带工具条（适应窗口/锁定）点了没反应，关掉，用下面的按钮代替
        show_controls=False,
        allow_new_edges=True,
        animate_new_edges=True,
        get_node_on_click=True,
        get_edge_on_click=True,
        enable_node_menu=False,
        enable_edge_menu=False,
        enable_pane_menu=False,
        hide_watermark=True,
    )
    st.session_state["need_fit"] = False

    if new_state is not None:
        st.session_state["flow_state"] = new_state
        _state.absorb(new_state)

        # 点节点 → 自动选中并刷新编辑面板（组件会把被点的节点 id 放在 selected_id）
        sel = getattr(new_state, "selected_id", "") or ""
        node_ids = {n["id"] for n in st.session_state.get("flow_nodes") or []}
        if sel and sel in node_ids and st.session_state.get("edit_node") != sel:
            st.session_state["edit_node"] = sel
            st.rerun()

    # 节点信息卡：点中哪个节点，就在下面直接展示它的配置
    cur = st.session_state.get("edit_node") or ""
    if cur:
        node = next((n for n in st.session_state["flow_nodes"] if n["id"] == cur), None)
        if node:
            meta = _state.meta(node.get("choice", ""))
            st.info(
                "**当前节点**：%s ｜ 类型：%s ｜ 执行顺序：%s ｜ 备注：%s"
                % (node.get("label") or "未命名", meta.get("tag", "?"),
                   node.get("order", "?"), (node.get("brief") or "（空）")[:40])
            )

    # 执行 JSON
    st.divider()
    workflow, errors = _state.build_workflow()
    st.session_state["workflow"] = workflow
    st.session_state["workflow_errors"] = errors

    if nodes:
        for err in errors:
            st.error(err)

    if workflow:
        parallel = [w for w in workflow if w["parallel_group"]]
        m1, m2 = st.columns([1, 3])
        m1.metric("步骤数", len(workflow))
        m2.caption("串行 %d 步" % (len(workflow) - len(parallel))
                   + ("；并行 %d 步（同组同时跑）" % len(parallel) if parallel else ""))
        with st.expander("预览执行 JSON", expanded=False):
            st.json(workflow, expanded=True)
