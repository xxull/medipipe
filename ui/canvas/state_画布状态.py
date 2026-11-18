# -*- coding: utf-8 -*-
"""
画布状态（canvas state）
=========================================================================
画布页的"数据与逻辑"部分，不碰界面。

职责：
    * 会话状态初始化（节点、连线、版本号）
    * 增删节点/连线
    * 逻辑图 → 组件状态（_build_state）
    * 组件状态 → 逻辑图（_absorb，只收坐标和新连线）
    * 逻辑图 → 执行 JSON（拓扑排序 + 并行分组）
    * 命名规则（自动 / 用原名 / 自己起 / 主模型起）

界面部分在同一个目录的另外两个文件里：
    edit_画布编辑.py   编辑器（连线面板、节点/连线表单）
    view_画布视图.py   画布渲染 + 结果 JSON

⚠️ 历史坑（都修在这里）
    * 加节点旧的消失 → 不按组件状态删节点
    * 拖动闪 → 结构不变不重建 + fragment
    * 同名插件 → scanner 里按路径去重 + key 加后缀
=========================================================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import streamlit as st

from core.loader_模块加载 import load as _load

_scanner = _load("core/scanner_插件扫描.py", "core_scanner")

# -------------------------------------------------------------------------
# 命名方式
# -------------------------------------------------------------------------
NAME_AUTO = "自动（类型+序号）"
NAME_ORIG = "用原名"
NAME_SELF = "我自己起"
NAME_MASTER = "主模型起名"
NAME_MODES = [NAME_AUTO, NAME_ORIG, NAME_SELF, NAME_MASTER]

DEFAULT_CHOICE = "网页抓取"


# -------------------------------------------------------------------------
# 清单（扫描结果，缓存在 session）
# -------------------------------------------------------------------------
def catalog() -> Dict[str, Dict[str, Any]]:
    if not st.session_state.get("catalog"):
        st.session_state["catalog"] = _scanner.build_catalog(
            extra_dirs=st.session_state.get("extra_dirs") or [],
            with_models=bool(st.session_state.get("with_models", True)),
            extra_plugins=st.session_state.get("disk_plugins") or [],
            deep_models=bool(st.session_state.get("deep_models")),
        )
    return st.session_state["catalog"]


def rescan(with_models: bool = False, deep: bool = False) -> None:
    if with_models:
        st.session_state["with_models"] = True
    if deep:
        st.session_state["deep_models"] = True
    st.session_state["catalog"] = _scanner.build_catalog(
        extra_dirs=st.session_state.get("extra_dirs") or [],
        with_models=bool(st.session_state.get("with_models", True)),
        extra_plugins=st.session_state.get("disk_plugins") or [],
        deep_models=bool(st.session_state.get("deep_models")),
    )


def cat_keys() -> List[str]:
    return list(catalog().keys())


def meta(choice: str) -> Dict[str, Any]:
    return catalog().get(choice, {})


# -------------------------------------------------------------------------
# 会话状态
# -------------------------------------------------------------------------
def init() -> None:
    st.session_state.setdefault("extra_dirs", [])
    st.session_state.setdefault("with_models", True)
    st.session_state.setdefault("disk_plugins", [])
    st.session_state.setdefault("deep_models", False)
    st.session_state.setdefault("flow_nodes", [])
    st.session_state.setdefault("flow_edges", [])
    st.session_state.setdefault("node_seq", 0)
    st.session_state.setdefault("edge_seq", 0)
    st.session_state.setdefault("flow_state", None)
    st.session_state.setdefault("graph_ver", 0)
    st.session_state.setdefault("built_ver", -1)
    st.session_state.setdefault("need_fit", True)
    st.session_state.setdefault("edit_node", "")
    st.session_state.setdefault("edit_edge", "")


def bump() -> None:
    """结构变了 → 下次重建画布。"""
    st.session_state["graph_ver"] += 1


# -------------------------------------------------------------------------
# 命名
# -------------------------------------------------------------------------
def auto_name(choice: str) -> str:
    used = [n.get("label", "") for n in st.session_state["flow_nodes"]]
    short = choice[:2]
    i = 1
    while "%s%d" % (short, i) in used:
        i += 1
    return "%s%d" % (short, i)


def name_for(choice: str, mode: str) -> str:
    if mode == NAME_ORIG:
        return choice
    return auto_name(choice)


def display_name(n: Dict[str, Any]) -> str:
    """画布上显示的文字："抓取1｜插件"；没命名就显示"请输入"。"""
    name = n.get("label") or "请输入"
    tag = meta(n["choice"]).get("tag", "")
    return "%s｜%s" % (name, tag) if tag else name


# -------------------------------------------------------------------------
# 增删
# -------------------------------------------------------------------------
def add_node(choice: str) -> None:
    st.session_state["node_seq"] += 1
    n = st.session_state["node_seq"]
    st.session_state["flow_nodes"].append(
        {
            "id": "n%d" % n,
            "label": "",              # 空 = 请输入
            "choice": choice,
            "name_mode": NAME_AUTO,
            "brief": "",
            "pos": (80 + ((n - 1) % 3) * 200, 40 + ((n - 1) // 3) * 120),
        }
    )
    st.session_state["edit_node"] = "n%d" % n
    bump()


def delete_node(nid: str) -> None:
    if not nid:
        return
    st.session_state["flow_nodes"] = [x for x in st.session_state["flow_nodes"] if x["id"] != nid]
    st.session_state["flow_edges"] = [
        e for e in st.session_state["flow_edges"] if e["source"] != nid and e["target"] != nid
    ]
    st.session_state["edit_node"] = ""
    bump()


def delete_edge(eid: str) -> None:
    if not eid:
        return
    st.session_state["flow_edges"] = [e for e in st.session_state["flow_edges"] if e["id"] != eid]
    st.session_state["edit_edge"] = ""
    bump()


def add_edge(src: str, dst: str) -> str:
    """手动连一条线。返回错误信息，空串代表成功。"""
    if not src or not dst:
        return "先选「从」和「到」两个节点"
    if src == dst:
        return "不能自己连自己"
    for e in st.session_state["flow_edges"]:
        if e["source"] == src and e["target"] == dst:
            return "这两个节点已经连过了"
    st.session_state["edge_seq"] += 1
    st.session_state["flow_edges"].append(
        {"id": "e%d" % st.session_state["edge_seq"], "source": src, "target": dst, "note": ""}
    )
    bump()
    return ""


def clear() -> None:
    st.session_state["flow_nodes"] = []
    st.session_state["flow_edges"] = []
    st.session_state["flow_state"] = None
    st.session_state["edit_node"] = ""
    st.session_state["edit_edge"] = ""
    st.session_state["need_fit"] = True
    bump()


# -------------------------------------------------------------------------
# 撤销（存最近 10 步快照）
# -------------------------------------------------------------------------
def snapshot() -> None:
    import copy

    stack = st.session_state.setdefault("undo_stack", [])
    stack.append(
        {
            "nodes": copy.deepcopy(st.session_state["flow_nodes"]),
            "edges": copy.deepcopy(st.session_state["flow_edges"]),
        }
    )
    del stack[:-10]


def undo() -> bool:
    stack = st.session_state.get("undo_stack") or []
    if not stack:
        return False
    last = stack.pop()
    st.session_state["flow_nodes"] = last["nodes"]
    st.session_state["flow_edges"] = last["edges"]
    st.session_state["flow_state"] = None
    st.session_state["built_ver"] = -1
    st.session_state["need_fit"] = True
    bump()
    return True


# -------------------------------------------------------------------------
# 逻辑图 ↔ 组件
# -------------------------------------------------------------------------
def build_state() -> Any:
    from streamlit_flow.elements import StreamlitFlowEdge, StreamlitFlowNode
    from streamlit_flow.state import StreamlitFlowState

    nodes = [
        StreamlitFlowNode(
            id=n["id"],
            pos=n["pos"],
            data={"label": display_name(n)},
            node_type="default",
            # 连线口方向：默认下出上入，用户可以在节点表单里改。
            # 每个节点左右上下都只有一个口，但支持接多条线：
            #   上面接多条 → 全部完成后才执行（引擎按依赖拓扑跑）
            #   下面接多条 → 同一份输出广播给下游
            source_position=n.get("source_pos") or "bottom",
            target_position=n.get("target_pos") or "top",
            draggable=True,
            selectable=True,
            deletable=False,
        )
        for n in st.session_state["flow_nodes"]
    ]
    edges = [
        StreamlitFlowEdge(
            id=e["id"],
            source=e["source"],
            target=e["target"],
            label=e.get("note", ""),
            animated=True,
            marker_end={"type": "arrowclosed"},
            deletable=False,
            focusable=True,
        )
        for e in st.session_state["flow_edges"]
    ]
    return StreamlitFlowState(nodes, edges)


def absorb(state: Any) -> None:
    """只收坐标和新连线，绝不删节点（组件返回值会慢一拍）。"""
    if state is None:
        return

    comp_nodes = list(getattr(state, "nodes", []) or [])
    pos_map: Dict[str, Tuple[float, float]] = {}
    for cn in comp_nodes:
        pos = getattr(cn, "position", None) or getattr(cn, "pos", None)
        if isinstance(pos, dict) and "x" in pos:
            pos_map[cn.id] = (pos["x"], pos["y"])

    for n in st.session_state["flow_nodes"]:
        if n["id"] in pos_map:
            n["pos"] = pos_map[n["id"]]

    known = {e["id"] for e in st.session_state["flow_edges"]}
    valid = {n["id"] for n in st.session_state["flow_nodes"]}
    for ce in getattr(state, "edges", []) or []:
        if ce.id in known or ce.source not in valid or ce.target not in valid:
            continue
        st.session_state["flow_edges"].append(
            {"id": ce.id, "source": ce.source, "target": ce.target, "note": getattr(ce, "label", "") or ""}
        )
        known.add(ce.id)


# -------------------------------------------------------------------------
# 执行 JSON
# -------------------------------------------------------------------------
def build_workflow() -> Tuple[List[Dict[str, Any]], List[str]]:
    nodes = {n["id"]: n for n in st.session_state["flow_nodes"]}
    edges = st.session_state["flow_edges"]
    errors: List[str] = []

    if not nodes:
        return [], ["画布是空的，先点「＋ 添加节点」"]

    out_map: Dict[str, List[str]] = {nid: [] for nid in nodes}
    in_deg: Dict[str, int] = {nid: 0 for nid in nodes}
    parents: Dict[str, set] = {nid: set() for nid in nodes}
    for e in edges:
        if e["source"] in nodes and e["target"] in nodes:
            out_map[e["source"]].append(e["target"])
            in_deg[e["target"]] += 1
            parents[e["target"]].add(e["source"])

    queue = sorted([nid for nid, d in in_deg.items() if d == 0])
    order: List[str] = []
    deg = dict(in_deg)
    while queue:
        cur = queue.pop(0)
        order.append(cur)
        for nxt in out_map[cur]:
            deg[nxt] -= 1
            if deg[nxt] == 0:
                queue.append(nxt)
        queue.sort()

    if len(order) != len(nodes):
        # 有环时不要返回“看起来能跑”的 workflow，否则选项 3 会按错误顺序执行。
        return [], errors + ["图里有环（A→B→A），请检查连线"]

    # 并行：只允许“同一个父节点的、且没有第二个父节点”的兄弟节点同组。
    # 这样 A→B、A→C、B→C 时 C 不会被错误地和 B 并行。
    parallel_of: Dict[str, str] = {}
    for parent, children in out_map.items():
        if len(children) <= 1:
            continue
        candidates = [c for c in children if parents[c] == {parent}]
        if len(candidates) <= 1:
            continue
        group = "g_" + parent
        for child in candidates:
            parallel_of[child] = group

    workflow = []
    for i, nid in enumerate(order, start=1):
        n = nodes[nid]
        m = meta(n["choice"])
        incoming = [e for e in edges if e["target"] == nid]
        workflow.append(
            {
                # step 必须是唯一节点 id；key 才是插件类型。
                # 两个同类型插件节点如果都用 step=plugin_key，状态灯和插件映射会互相覆盖。
                "step": nid,
                "key": m.get("key", nid),
                "name": n.get("label") or n["choice"],
                "kind": m.get("kind", "unknown"),
                "tag": m.get("tag", ""),
                "needs": m.get("needs", {}),
                "model": m.get("model", ""),
                "file": m.get("file", ""),
                "brief": n.get("brief", ""),
                "note": "；".join(e["note"] for e in incoming if e.get("note")),
                "order": i,
                "parallel_group": parallel_of.get(nid, ""),
            }
        )
    return workflow, errors
