# -*- coding: utf-8 -*-
"""插件示例：通用字段抽取。

从一段文本里抽出 title / summary / keywords。先本地规则，缺字段再问主模型。
字段名是通用示例，不代表任何行业模型。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from base_基类 import BasePlugin

FIELDS = ("title", "summary", "keywords")


class FieldExtractor(BasePlugin):
    """通用字段抽取示例。"""

    name = "字段抽取"
    NEEDS = {"network": False, "model": True}
    OUTPUT_FIELDS = list(FIELDS)

    def execute(self, text_data: str) -> str:
        return json.dumps(self.execute_rich({"text": text_data}), ensure_ascii=False)

    def _local(self, text: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        lines = [x.strip() for x in text.splitlines() if x.strip()]

        m = re.search(r"(?im)^\s*(?:标题|title)\s*[：:]\s*(.+)$", text)
        if m:
            out["title"] = m.group(1).strip()[:80]
        elif lines:
            out["title"] = re.sub(r"\s+", " ", lines[0])[:80]

        m = re.search(r"(?ims)^\s*(?:摘要|summary)\s*[：:]\s*(.+?)(?:\n\s*\n|$)", text)
        if m:
            out["summary"] = re.sub(r"\s+", " ", m.group(1)).strip()[:300]
        else:
            body = re.sub(r"\s+", " ", text).strip()
            out["summary"] = body[:200]

        m = re.search(r"(?im)^\s*(?:关键词|关键字|keywords?)\s*[：:]\s*(.+)$", text)
        if m:
            out["keywords"] = [x.strip() for x in re.split(r"[,，、;；\s]+", m.group(1)) if x.strip()][:8]
        else:
            # 无关键词行时，取文本中较长的重复片段作占位，不调用模型。
            words = re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,8}", text)
            counts = {}
            for w in words:
                counts[w] = counts.get(w, 0) + 1
            out["keywords"] = [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:5]]
        return out

    def execute_rich(self, ctx: dict) -> dict:
        raw = str(ctx.get("original") or ctx.get("text") or "").strip()
        if not raw:
            raise RuntimeError("抽取插件收到空文本")
        data = self._local(raw)
        missing = [f for f in FIELDS if not data.get(f)]
        if not missing:
            return data

        master = ctx.get("master")
        if master is None:
            data["missing"] = missing
            return data

        system = (
            "你是信息抽取器。只输出 JSON 对象，字段为 title、summary、keywords。"
            "keywords 是字符串数组。不要解释。"
        )
        user = "文本：\n%s\n\n本地已抽到：%s\n还缺：%s" % (
            raw[:1500], json.dumps(data, ensure_ascii=False), "、".join(missing))
        try:
            got = master.chat_json(system, user, max_tokens=500)
        except Exception:
            got = {}
        for key in FIELDS:
            value = got.get(key)
            if value and not data.get(key):
                if key == "keywords":
                    if isinstance(value, str):
                        value = [x.strip() for x in re.split(r"[,，、;；\s]+", value) if x.strip()]
                    data[key] = list(value)[:8]
                else:
                    data[key] = str(value)[:300]
        data["missing"] = [f for f in FIELDS if not data.get(f)]
        return data
