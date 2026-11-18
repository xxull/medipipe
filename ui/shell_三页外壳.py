# -*- coding: utf-8 -*-
"""
应用外壳（shell）
=========================================================================
只做三件事：
    1. 配好页面（标题、宽屏）
    2. 顶部放一个「选项」切换条（选项 1 / 2 / 3）
    3. 把选中的那一页渲染出来

业务逻辑一律不写在这里 —— 这是"微内核"的意思：
外壳只负责导航，具体干活在 ui/page*.py 和 plugins/ 里。
=========================================================================
"""

from __future__ import annotations

import streamlit as st

from core.loader_模块加载 import load

# 按文件名加载三个页面模块（文件名带中文，模块别名用纯英文）
_page1 = load("ui/page1_主模型配置.py", "ui_page1")
_page2 = load("ui/page2_画布编排.py", "ui_page2")
_page3 = load("ui/page3_开始工作.py", "ui_page3")

PAGES = [
    ("选项 1 · 主模型配置", _page1),
    ("选项 2 · 画布编排", _page2),
    ("选项 3 · 开始工作", _page3),
]


def main() -> None:
    """应用入口：画外壳 + 渲染当前页。"""
    st.set_page_config(page_title="Framework A · 数据兵工厂", page_icon="🏭", layout="wide")

    # ---------- 顶部：标题 + 选项切换 ----------
    st.title("🏭 Framework A · 离线数据生产兵工厂")
    st.caption("主模型监督 · 轻量插件干活 · 串行 + 并行混合调度")

    labels = [p[0] for p in PAGES]

    # 支持 ?page=2 直接跳到某一页（方便截图、也方便你收藏特定页面）
    try:
        qp = st.query_params.get("page")
        if qp and str(qp).isdigit():
            idx_qp = max(0, min(len(labels) - 1, int(qp) - 1))
            st.session_state["current_page"] = labels[idx_qp]
    except Exception:
        pass

    current = st.session_state.get("current_page", labels[0])
    idx = labels.index(current) if current in labels else 0

    choice = st.radio(
        "选择功能",
        labels,
        index=idx,
        horizontal=True,
        label_visibility="collapsed",
        key="radio_current_page",
    )
    st.session_state["current_page"] = choice
    st.divider()

    # ---------- 渲染当前页 ----------
    for label, module in PAGES:
        if label == choice:
            module.render()
            break


if __name__ == "__main__":
    main()
