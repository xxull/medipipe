# -*- coding: utf-8 -*-
"""
Framework B 的主模型配置（b_配置）
=========================================================================
B 的默认能力全部走本地模型（bge-m3 检索、qwen3-vl 总结/翻译），
不配 Key 也能完整使用。

配 Key 的唯一价值：总结和翻译质量更高（主模型比本地 4B 强很多）。

Key 存在哪？
-------------------------------------------------------------------------
    和 Framework A 同一个 `.env` 的 `MY_LLM_KEY`。
    两个框架共用一份配置，不用来回填。
    `.env` 已被 .gitignore 排除。

用法：
    from framework_b import b_配置
    b_配置.get_key()            # 读 Key
    b_配置.set_key("sk-...")    # 写 Key（空串 = 删除）
    b_配置.test_key()           # 发一个小请求验证
=========================================================================
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Tuple

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
ENV_KEY = "MY_LLM_KEY"
BASE_URL = "https://api.deepseek.com"
MODEL = "deepseek-chat"


def get_key() -> str:
    """读 Key：先环境变量，再 .env。"""
    k = os.environ.get(ENV_KEY, "").strip()
    if k:
        return k
    if not ENV_PATH.exists():
        return ""
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(ENV_KEY + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def set_key(key: str) -> bool:
    """写 Key 到 .env（空串就删掉那一行）。返回是否成功。"""
    key = (key or "").strip()
    lines = []
    if ENV_PATH.exists():
        try:
            lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []

    out, done = [], False
    for line in lines:
        if line.strip().startswith(ENV_KEY + "="):
            if key:
                out.append("%s=%s" % (ENV_KEY, key))
                done = True
            # key 为空 → 跳过这行（等于删除）
        else:
            out.append(line)
    if key and not done:
        out.append("%s=%s" % (ENV_KEY, key))

    try:
        ENV_PATH.write_text("\n".join(out).strip() + "\n", encoding="utf-8")
    except Exception:
        return False

    if key:
        os.environ[ENV_KEY] = key
    else:
        os.environ.pop(ENV_KEY, None)
    return True


def mask(key: str) -> str:
    """显示用：只露前 6 位和后 4 位。"""
    k = (key or "").strip()
    if len(k) <= 12:
        return "已配置" if k else "未配置"
    return "%s…%s" % (k[:6], k[-4:])


def test_key(key: str = "") -> Tuple[bool, str]:
    """
    发一个最小请求验证 Key。返回 (是否可用, 说明)。

    只花 1 个 token 左右（约 0.0001 元）。
    """
    k = (key or get_key()).strip()
    if not k:
        return False, "没有 Key"

    import json
    import urllib.request

    payload = json.dumps({
        "model": MODEL,
        "messages": [{"role": "user", "content": "回复：ok"}],
        "max_tokens": 5,
        "temperature": 0,
    }).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + "/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + k,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        msg = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return True, "可用（返回：%s）" % (msg or "空")[:40]
    except Exception as exc:
        text = str(exc)
        if "401" in text or "Unauthorized" in text:
            return False, "Key 无效（401）"
        if "402" in text or "balance" in text.lower():
            return False, "余额不足（402）"
        if "429" in text:
            return False, "限流（429），稍后再试"
        return False, "连接失败：%s" % text[:80]


def make_master():
    """按当前 Key 建主模型客户端；没 Key 返回 None。"""
    key = get_key()
    if not key:
        return None
    try:
        from core.llm_主模型 import MasterLLM

        return MasterLLM(key=key, budget_cny=0.2, timeout=60)
    except Exception:
        return None


if __name__ == "__main__":
    print("Key：", mask(get_key()))
    print("测试：", test_key())
