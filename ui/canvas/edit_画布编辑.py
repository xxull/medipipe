# -*- coding: utf-8 -*-
"""
画布编辑器（canvas editor）
=========================================================================
界面上的三块"编辑"：
    ① 连一条线（选两个节点点一下就连上，不依赖拖拽）
    ② 选节点 → 改名 / 换类型 / 写备注 / 删除
    ③ 选连线 → 写注释 / 删除

数据操作全部委托给 state_画布状态.py，这里只管画控件。
=========================================================================
"""

from __future__ import annotations

from typing import Any, Dict

import streamlit as st

from core.loader_模块加载 import load as _load

_state = _load("ui/canvas/state_画布状态.py", "ui_canvas_state")


def _node_label(n: Dict[str, Any]) -> str:
    return n.get("label") or "未命名"


def connect_panel() -> None:
    """① 连一条线。"""
    nodes = st.session_state["flow_nodes"]
    edges = st.session_state["flow_edges"]
    if len(nodes) < 2:
        return

    with st.expander("🔗 连一条线（选两个节点，点一下就连上）", expanded=(len(edges) == 0)):
        label2id = {("%s［%s］" % (_node_label(n), n["id"])): n["id"] for n in nodes}
        keys = list(label2id.keys())
        c1, c2, c3 = st.columns([1.2, 1.2, 0.6])
        with c1:
            a = st.selectbox("从", keys, key="edge_from")
        with c2:
            b = st.selectbox("到", keys, index=min(1, len(keys) - 1), key="edge_to")
        with c3:
            st.write("")
            if st.button("连上", key="do_add_edge", width="stretch"):
                err = _state.add_edge(label2id[a], label2id[b])
                if err:
                    st.warning(err)
                else:
                    st.rerun()


def node_form(sel_node: str) -> None:
    """② 节点编辑表单。"""
    nodes = st.session_state["flow_nodes"]
    node = next((n for n in nodes if n["id"] == sel_node), None)
    if not node:
        return

    keys = _state.cat_keys()
    c1, c2, c3 = st.columns([1.3, 1.3, 0.6])

    with c1:
        idx = keys.index(node["choice"]) if node["choice"] in keys else 0
        new_choice = st.selectbox("类型（从本机扫描）", keys, index=idx, key="chc_" + sel_node)
        if new_choice != node["choice"]:
            node["choice"] = new_choice
            node["label"] = _state.name_for(new_choice, node.get("name_mode", _state.NAME_AUTO))
            _state.bump()

    with c2:
        mode_idx = _state.NAME_MODES.index(node.get("name_mode", _state.NAME_AUTO))
        new_mode = st.selectbox("怎么起名", _state.NAME_MODES, index=mode_idx, key="mode_" + sel_node)
        if new_mode != node.get("name_mode"):
            node["name_mode"] = new_mode
            if new_mode in (_state.NAME_AUTO, _state.NAME_ORIG):
                node["label"] = _state.name_for(node["choice"], new_mode)
                _state.bump()

    with c3:
        st.write("")
        if st.button("删除", key="del_" + sel_node, width="stretch"):
            _state.delete_node(sel_node)
            st.rerun()

    # 名字
    if node.get("name_mode") == _state.NAME_SELF:
        val = st.text_input("名字", value=node.get("label", ""), key="lbl_" + sel_node)
        if val != node.get("label", ""):
            node["label"] = val
            _state.bump()
    elif node.get("name_mode") == _state.NAME_MASTER:
        cc1, cc2 = st.columns([1, 3])
        with cc1:
            if st.button("让主模型起名", key="mname_" + sel_node, width="stretch"):
                ok, name = _ask_master_name(node)
                if ok:
                    node["label"] = name
                    _state.bump()
                    st.success("起好了：%s" % name)
                else:
                    st.warning(name)
        with cc2:
            st.caption("当前名字：%s" % (node.get("label") or "（还没起）"))
    else:
        st.caption("名字：%s（自动）" % (node.get("label") or "请输入"))

    # 备注：给主模型的指令
    kind = _state.meta(node["choice"]).get("kind", "")
    hint = {
        "master": "告诉主模型干什么，比如「检查上面这段代码有没有错」",
        "model": "具体命令，比如「把这段文本压到 500 字」",
        "plugin": "这一步要做什么，比如「抓取网页正文」",
    }.get(kind, "这一步要做什么")
    node["brief"] = st.text_area(
        "备注（主模型会照着这个调度）",
        value=node.get("brief", ""),
        height=68,
        placeholder=hint,
        key="brief_" + sel_node,
    )

    m = _state.meta(node["choice"])
    if m.get("file"):
        st.caption("来源：%s" % m["file"])
    if m.get("needs", {}).get("network"):
        st.warning("这个插件**会联网**，敏感数据别直接丢进去")

    # ---- 连线口方向 ----
    st.caption("连线口方向（每个节点上下各一个口，可以接多条线："
               "上面接多条=全部完成才执行；下面接多条=输出广播给多个下游）")
    pp1, pp2 = st.columns(2)
    dirs = ["bottom", "top", "left", "right"]
    names = {"bottom": "下", "top": "上", "left": "左", "right": "右"}
    with pp1:
        cur_out = node.get("source_pos") or "bottom"
        out = st.selectbox("出口方向", dirs, index=dirs.index(cur_out) if cur_out in dirs else 0,
                           format_func=lambda x: names[x], key="sp_" + sel_node)
        if out != cur_out:
            node["source_pos"] = out
            _state.bump()
    with pp2:
        cur_in = node.get("target_pos") or "top"
        inn = st.selectbox("入口方向", dirs, index=dirs.index(cur_in) if cur_in in dirs else 1,
                           format_func=lambda x: names[x], key="tp_" + sel_node)
        if inn != cur_in:
            node["target_pos"] = inn
            _state.bump()

    # ---- 从本机挑插件文件 ----
    if m.get("kind") == "plugin":
        if st.button("📄 从本机选择插件文件（.py）", key="pickp_" + sel_node):
            try:
                from core.picker_本机选择 import pick_file

                picked = pick_file("选择插件文件", "Python 插件|*.py|所有文件|*.*")
            except Exception as exc:
                picked = ""
                st.warning("打不开文件选择框：%s" % exc)
            if picked:
                # 扫描器认的是 disk_plugins 这个键，别自己造一个新键
                st.session_state.setdefault("disk_plugins", [])
                if picked not in st.session_state["disk_plugins"]:
                    st.session_state["disk_plugins"].append(picked)
                _state.rescan()
                st.success("已加入：%s（类型下拉里现在能选到）" % picked)
                st.rerun()


def edge_form(sel_edge: str) -> None:
    """③ 连线编辑表单。"""
    edges = st.session_state["flow_edges"]
    nodes = st.session_state["flow_nodes"]
    edge = next((e for e in edges if e["id"] == sel_edge), None)
    if not edge:
        return

    names = {n["id"]: _node_label(n) for n in nodes}
    st.markdown("**连线：%s → %s**" % (names.get(edge["source"], "?"), names.get(edge["target"], "?")))
    ec1, ec2 = st.columns([3.2, 0.8])
    with ec1:
        note = st.text_input("线上注释", value=edge.get("note", ""), key="edge_" + sel_edge)
        if note != edge.get("note", ""):
            edge["note"] = note
            _state.bump()
    with ec2:
        st.write("")
        if st.button("删除线", key="deledge_" + sel_edge, width="stretch"):
            _state.delete_edge(sel_edge)
            st.rerun()


def _ask_master_name(node: Dict[str, Any]):
    """让主模型给这个节点起个短名字。"""
    from core.llm_主模型 import LLMError, MasterLLM

    key = st.session_state.get("main_api_key") or ""
    if not key:
        return False, "先在「选项 1」配好主模型 Key"

    m = _state.meta(node["choice"])
    try:
        master = MasterLLM(
            key=key,
            base=st.session_state.get("main_base") or "https://api.deepseek.com",
            model=st.session_state.get("main_model") or "deepseek-chat",
            budget_cny=0.02,
            timeout=20,
        )
        prompt = (
            "给下面这个处理步骤起一个中文短名（2~4 个字，不要标点，不要解释）：\n"
            "类型：%s\n标签：%s\n备注：%s\n只输出名字本身。"
            % (node["choice"], m.get("tag", ""), node.get("brief") or "（无）")
        )
        name = master.chat("你在给数据流水线的步骤起名。", prompt, max_tokens=20).strip()
        name = name.strip("「」\"' \n\r\t：:")
        if not name:
            return False, "主模型没给出名字，再试一次"
        return True, name[:8]
    except LLMError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, "调用失败：%s" % exc
