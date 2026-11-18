# -*- coding: utf-8 -*-
"""
页面 1：主模型配置（page1）
=========================================================================
对应你设计的「选项 1」。

界面上只有两样东西：
    1. 下拉框：选主模型厂商（DeepSeek / Kimi / 通义 / OpenAI 兼容自定义）
    2. 密码框：填这个厂商的 API Key

填完点「确认」，存进 st.session_state，后面「选项 3」执行时用。

为什么存 session_state 而不是 .env？
-------------------------------------------------------------------------
默认只存 st.session_state，刷新就没了，更安全。
勾选「记住」才会写入项目根目录的 .env（明文），适合本机长期使用；
.env 已被 .gitignore 排除，不要提交到仓库。

安全约定
-------------------------------------------------------------------------
* 默认只进内存，不打印、不进日志
* 只有勾选「记住」才写入 .env（明文）
* 页面上只显示"已配置"，不回显 Key
=========================================================================
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
ENV_KEY = "MY_LLM_KEY"


def _load_saved_key() -> str:
    """从 .env 读存过的 Key（读不到返回空串）。"""
    try:
        if not ENV_PATH.exists():
            return ""
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(ENV_KEY + "="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return ""


def _save_key(key: str) -> None:
    """把 Key 写进 .env（key 为空就删掉那一行）。"""
    try:
        lines = []
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        lines = [x for x in lines if not x.strip().startswith(ENV_KEY + "=")]
        if key:
            lines.append("%s=%s" % (ENV_KEY, key))
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # 同时放进环境变量，方便其它模块读
        if key:
            os.environ[ENV_KEY] = key
        else:
            os.environ.pop(ENV_KEY, None)
    except Exception as exc:
        st.warning("写 .env 失败：%s" % exc)

# 支持的厂商：显示名 → 接口地址 + 默认模型
# 加新厂商只需要在这里加一行，页面自动出现
PROVIDERS = {
    "DeepSeek（深度求索）": {
        "base": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "Kimi（月之暗面）": {
        "base": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
    },
    "通义千问（阿里云）": {
        "base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "自定义（OpenAI 兼容）": {
        "base": "",
        "model": "",
    },
}


def render() -> None:
    """渲染"选项 1"整页。"""
    st.subheader("① 主模型配置")
    st.caption("主模型只负责**监督**：读指令、出计划、验收结果。它不直接处理数据。")

    # ---------- 1. 选厂商 ----------
    names = list(PROVIDERS.keys())
    current = st.session_state.get("main_provider", names[0])
    idx = names.index(current) if current in names else 0

    provider = st.selectbox("主模型类型", names, index=idx, key="sel_main_provider")
    st.session_state["main_provider"] = provider

    conf = PROVIDERS[provider]

    # ---------- 2. 自定义时需要填地址和模型名 ----------
    if provider.startswith("自定义"):
        base = st.text_input(
            "接口地址（base_url）",
            value=st.session_state.get("main_base", ""),
            placeholder="https://你的服务/v1",
        )
        model = st.text_input(
            "模型名",
            value=st.session_state.get("main_model", ""),
            placeholder="例如 gpt-4o-mini",
        )
        st.session_state["main_base"] = base.strip()
        st.session_state["main_model"] = model.strip()
    else:
        st.session_state["main_base"] = conf["base"]
        st.session_state["main_model"] = conf["model"]
        st.caption("接口地址：%s" % conf["base"])
        st.caption("默认模型：%s" % conf["model"])

    # ---------- 3. 填 Key ----------
    # 启动时：如果 .env 里存过 Key，自动读进来（省得每次重填）
    if not st.session_state.get("main_api_key") and _load_saved_key():
        st.session_state["main_api_key"] = _load_saved_key()

    key = st.text_input(
        "API Key",
        value=st.session_state.get("main_api_key", ""),
        type="password",
        placeholder="sk-...",
        help="默认只存在本次会话；勾上「记住」会写进项目里的 .env（明文，自己电脑上才这么用）",
    )

    remember = st.checkbox("记住 Key（写进 .env，下次打开自动填）", value=bool(_load_saved_key()))

    c1, c2 = st.columns([1, 1])
    with c1:
        if st.button("确认这个 Key", width="stretch"):
            if not key.strip():
                st.warning("Key 是空的，先填一个")
            else:
                st.session_state["main_api_key"] = key.strip()
                if remember:
                    _save_key(key.strip())
                    st.success("已保存到 .env（下次自动填）")
                else:
                    st.success("已记到本次会话（不落盘）")
    with c2:
        if st.button("清除 Key", width="stretch"):
            st.session_state["main_api_key"] = ""
            _save_key("")
            st.info("已清除（.env 里也清掉了）")

    # ---------- 4. 状态回显（只显示有没有，不显示内容） ----------
    saved = st.session_state.get("main_api_key", "")
    st.divider()
    if saved:
        st.success("主模型已就绪：%s / %s（Key 长度 %d）"
                   % (provider, st.session_state.get("main_model"), len(saved)))
    else:
        st.info("还没配置主模型。没 Key 也能跑，只是没有监督和验收，纯本地执行。")
