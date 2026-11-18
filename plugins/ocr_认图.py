# -*- coding: utf-8 -*-
"""
认图插件（ocr_认图）
=========================================================================
把一张图变成文字描述 / 关键词。用本地 Ollama 的多模态模型，不联网、不花钱。

输入
-------------------------------------------------------------------------
    * 本地图片路径（jpg / png / webp / bmp）
    * 或图片网址（http/https）

节点备注（brief）里可以写：
    * 一句指令，比如「描述这张图，列出 5 个关键词」
    * 或 `model=qwen3-vl:4b` 指定模型

输出
-------------------------------------------------------------------------
    {"text": 描述文本, "model": 用的模型}

为什么不自己跑 OCR 库？
-------------------------------------------------------------------------
    纯 OCR 只能出字，出不了"这张图是什么"。
    多模态模型能同时给描述和关键词，正好对上"认图→关键词"这个用途。
    如果只要文字（比如扫描件），那是另一个插件的事。
=========================================================================
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from typing import Any, Dict, Tuple

from base_基类 import BasePlugin

DEFAULT_MODEL = "qwen3-vl:4b"
DEFAULT_PROMPT = "描述这张图，并列出 5 个关键词。用中文，不要客套。"
MAX_BYTES = 20 * 1024 * 1024      # 单张图上限 20MB


class OCRVision(BasePlugin):
    """图片 → 描述 + 关键词。"""

    name = "认图"
    NEEDS = {"network": False, "model": True}
    OUTPUT_FIELDS = ["text"]

    def execute(self, text_data: str) -> str:
        result = self.execute_rich({"text": text_data})
        return str(result.get("text", ""))

    def execute_rich(self, ctx: dict) -> Dict[str, Any]:
        target = str(ctx.get("text") or "").strip().strip('"').strip("'")
        if not target:
            raise RuntimeError("认图插件需要图片路径或网址，但收到的是空的")

        brief = str(ctx.get("brief") or "")
        model = self._pick_model(brief)
        prompt = self._pick_prompt(brief)

        data, label = self._load_image(target)
        if len(data) > MAX_BYTES:
            raise RuntimeError("图片太大（%.1f MB），先压缩一下" % (len(data) / 1024 / 1024))

        text = self._describe(data, model, prompt)

        # 顺手从描述里抠出"关键词"那一行（抠不到就算了，不影响主流程）
        keywords = []
        for line in text.splitlines():
            if re.search(r"关键词|keywords", line, re.I):
                raw = re.split(r"[:：]", line, maxsplit=1)[-1]
                keywords = [x.strip(" ·-、,") for x in re.split(r"[、,，;；]", raw) if x.strip()]
                break

        return {
            "text": text,
            "keywords": keywords[:10],
            "model": model,
            "source": label,
            "paid": False,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_model(brief: str) -> str:
        m = re.search(r"model=([\w\-.:/]+)", brief or "")
        return m.group(1) if m else os.environ.get("FW_VISION_MODEL", DEFAULT_MODEL)

    @staticmethod
    def _pick_prompt(brief: str) -> str:
        # 备注里除了 model= 之外的话，就当指令用
        cleaned = re.sub(r"model=[\w\-.:/]+", "", brief or "").strip()
        return cleaned or DEFAULT_PROMPT

    @staticmethod
    def _load_image(target: str) -> Tuple[bytes, str]:
        """读本地文件或下载网址，返回 (字节, 说明)。"""
        if re.match(r"^https?://", target, re.I):
            # 复用项目的 URL 安全策略：拒绝内网/本机地址（防 SSRF）
            try:
                from core.url_safety import assert_public_http_url

                assert_public_http_url(target)
            except ImportError:
                pass                      # 单独跑插件时允许没有这个模块
            except ValueError as exc:
                raise RuntimeError("这个地址不允许访问：%s" % exc)

            import requests

            r = requests.get(
                target,
                timeout=60,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"},
            )
            r.raise_for_status()
            return r.content, target

        path = target
        if not os.path.exists(path):
            raise RuntimeError("找不到这张图：%s" % path)
        with open(path, "rb") as fp:
            return fp.read(), os.path.basename(path)

    @staticmethod
    def _describe(data: bytes, model: str, prompt: str) -> str:
        """调本地 Ollama 的多模态接口。"""
        try:
            from core.launcher_服务启动 import OLLAMA_BASE, ensure_ollama

            ok, msg = ensure_ollama(True)
            if not ok:
                raise RuntimeError("本地模型服务没起来：%s" % msg)
        except ImportError:
            OLLAMA_BASE = "http://127.0.0.1:11434"
        except RuntimeError:
            raise

        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "images": [base64.b64encode(data).decode("ascii")],
                "stream": False,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            OLLAMA_BASE + "/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                body = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError("认图失败（模型名对不对？Ollama 里有 %s 吗）：%s" % (model, exc))

        text = str(body.get("response") or "").strip()
        if not text:
            raise RuntimeError("模型没返回内容（图片可能太小/太糊，或模型不支持图片输入）")
        return text


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python plugins/ocr_认图.py <图片路径或网址>")
        raise SystemExit(0)
    p = OCRVision()
    print(json.dumps(p.execute_rich({"text": sys.argv[1], "brief": ""}), ensure_ascii=False, indent=2)[:800])
