# -*- coding: utf-8 -*-
"""
主控大模型客户端（Master LLM）
=========================================================================
整个框架里，"主 AI"只做三件事，**绝不碰大段原始数据**：

    1. 读指令 → 输出一句计划（"收到指令，将先执行……"）
    2. 验收 → 只看结果的**结构**（字段有没有、类型对不对），不看正文
    3. 报错辅助 → 干活失败时，看错误信息给出修正建议

为什么这么设计？
-------------------------------------------------------------------------
原始数据可能受协议约束（很多数据集禁止转给第三方 API），
而且大模型按 token 计费，一份完整数据几千字，多读一份就多几毛钱。
把"读原文"这件事全部交给本地辅 AI，成本能降一个数量级。

Key 读取顺序（BYOK）
-------------------------------------------------------------------------
    MY_LLM_KEY  →  MAIN_LLM_API_KEY  →  DEEPSEEK_API_KEY
前两个是框架自己的规范命名，最后一个是兼容现有的 DeepSeek 环境变量。
=========================================================================
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import requests

# -------------------------------------------------------------------------
# BYOK：优先从项目根目录的 .env 读 Key
# dotenv 是可选依赖，没装也不影响（只是不能自动读 .env）
# -------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

# -------------------------------------------------------------------------
# 计费：单位换算按"每百万 token 多少元"算，方便核对账单
# 这些数字请按你实际套餐改；DeepSeek 价格调整过几次，别当成永久准数。
# -------------------------------------------------------------------------
PRICE_INPUT_PER_M = 2.0    # 输入：元 / 百万 token
PRICE_OUTPUT_PER_M = 8.0   # 输出：元 / 百万 token

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class LLMError(Exception):
    """主模型调用相关的中文异常。"""


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """
    按优先级找一个可用的 Key。

    注意：这里只返回 Key 本身，不打印、不落盘、不进日志。
    """
    if explicit and explicit.strip():
        return explicit.strip()
    for name in ("MY_LLM_KEY", "MAIN_LLM_API_KEY", "DEEPSEEK_API_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    raise LLMError(
        "没有找到大模型 Key：请设置环境变量 MY_LLM_KEY（或 MAIN_LLM_API_KEY / DEEPSEEK_API_KEY）"
    )


@dataclass
class Usage:
    """累计用量（一次工作流 run 一个实例）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    cost_cny: float = 0.0
    timeline: List[Dict[str, Any]] = field(default_factory=list)

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.calls += 1
        self.cost_cny += (
            prompt_tokens / 1_000_000 * PRICE_INPUT_PER_M
            + completion_tokens / 1_000_000 * PRICE_OUTPUT_PER_M
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_cny": round(self.cost_cny, 6),
        }


class MasterLLM:
    """
    主模型客户端。

    特性
    ----
    * 自动重试（网络抖动、5xx）
    * 强制 JSON 模式，并且能从"模型多说了两句话"里把 JSON 抠出来
    * 预算保险丝：超过 budget_cny 直接拒绝再调，避免一夜跑掉几百块
    """

    def __init__(
        self,
        key: Optional[str] = None,
        base: str = DEFAULT_BASE,
        model: str = DEFAULT_MODEL,
        budget_cny: float = 1.0,
        timeout: int = 60,
    ) -> None:
        self.key = resolve_api_key(key)
        self.base = base.rstrip("/")
        self.model = model
        self.budget_cny = budget_cny
        self.timeout = timeout
        self.usage = Usage()

    # ---------- 底层调用 ----------
    def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 800,
        json_mode: bool = False,
        temperature: float = 0.2,
    ) -> str:
        if self.usage.cost_cny >= self.budget_cny:
            raise LLMError(
                "已达本次预算上限 %.2f 元（已花 %.4f 元），停止调用主模型"
                % (self.budget_cny, self.usage.cost_cny)
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last_error = ""
        for attempt in range(3):
            started = time.perf_counter()
            try:
                resp = requests.post(
                    self.base + "/chat/completions",
                    headers={
                        "Authorization": "Bearer " + self.key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                cost_ms = int((time.perf_counter() - started) * 1000)

                if resp.status_code == 401:
                    raise LLMError("Key 无效或已过期（401）")
                if resp.status_code == 402:
                    raise LLMError("账户余额不足（402）")
                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    last_error = "请求太频繁（429）"
                    continue
                if resp.status_code >= 500:
                    time.sleep(1.0 * (attempt + 1))
                    last_error = "服务端错误（%d）" % resp.status_code
                    continue
                if resp.status_code != 200:
                    raise LLMError("调用失败（HTTP %d）：%s" % (resp.status_code, resp.text[:200]))

                data = resp.json()
                usage = data.get("usage") or {}
                self.usage.add(
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                )
                self.usage.timeline.append(
                    {"kind": "llm", "ms": cost_ms, "tokens": usage.get("total_tokens")}
                )

                choices = data.get("choices") or []
                if not choices:
                    raise LLMError("模型没有返回 choices")
                return str(choices[0].get("message", {}).get("content") or "")

            except requests.exceptions.Timeout:
                last_error = "请求超时"
                time.sleep(1.0 * (attempt + 1))
            except requests.exceptions.ConnectionError as exc:
                last_error = "网络错误：%s" % exc
                time.sleep(1.0 * (attempt + 1))

        raise LLMError("主模型调用失败（重试 3 次）：%s" % last_error)

    # ---------- 便捷方法 ----------
    def chat_json(self, system: str, user: str, max_tokens: int = 800) -> Dict[str, Any]:
        """
        让模型输出 JSON，并把它解析成 dict。

        模型的通病是"我要 JSON，它给你 ```json ... ``` 外加一句解释"，
        所以这里先剥代码块，再正则抓第一个大括号对象，最后兜底报错。
        """
        raw = self.chat(system, user, max_tokens=max_tokens, json_mode=True)
        return parse_json_loose(raw)


def parse_json_loose(raw: str) -> Dict[str, Any]:
    """从可能带解释、带代码块的文本里，尽最大努力抠出 JSON 对象。"""
    text = (raw or "").strip()

    # 1) 去掉 ```json ... ``` 包裹
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    # 2) 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        if isinstance(obj, list):
            return {"items": obj}
    except json.JSONDecodeError:
        pass

    # 3) 抓第一个 {...}（贪婪匹配到最后一个 }，再不行就缩到第一个配对的）
    start = text.find("{")
    if start >= 0:
        depth = 0
        for idx in range(start, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : idx + 1])
                    except json.JSONDecodeError:
                        break

    raise LLMError("模型没有返回可解析的 JSON：%s" % text[:200])
