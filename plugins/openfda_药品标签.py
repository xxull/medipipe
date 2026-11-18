# -*- coding: utf-8 -*-
"""
药品标签来源插件（openfda_药品标签）
=========================================================================
从 openFDA 拉药品说明书的**结构化字段**。

为什么选 openFDA？
-------------------------------------------------------------------------
    * 官方公开 API，免费，不需要 Key（有速率限制）
    * 直接返回 JSON，字段规整，不用解析网页
    * 用它做"药品数据"的第一批，合规且干净

输入 / 输出
-------------------------------------------------------------------------
    输入（text）：药名，比如 "aspirin"、"metformin"
    输出：{"text": 摘要, "brand_name": ..., "generic_name": ...,
           "indications": ..., "dosage": ..., "warnings": ..., ...}

节点备注（brief）里可以写：
    limit=3      同一药名最多取几条（默认 1）
    field=generic_name  用哪个字段匹配（默认先 brand_name 再 generic_name）
=========================================================================
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from base_基类 import BasePlugin

API = "https://api.fda.gov/drug/label.json"
TIMEOUT = 20

#: 输出里保留哪些字段（顺序即入库列顺序）
KEEP_FIELDS = [
    "brand_name",
    "generic_name",
    "manufacturer",
    "product_type",
    "route",
    "indications",
    "dosage",
    "warnings",
    "contraindications",
]


class OpenFDALabel(BasePlugin):
    """按药名取药品标签（说明书）结构化字段。"""

    name = "药品标签"
    NEEDS = {"network": True, "model": False}
    OUTPUT_FIELDS = ["brand_name", "generic_name", "indications"]

    def execute(self, text_data: str) -> str:
        result = self.execute_rich({"text": text_data})
        return str(result.get("text", ""))

    def execute_rich(self, ctx: dict) -> Dict[str, Any]:
        name = str(ctx.get("text") or "").strip().strip('"').strip("'")
        if not name:
            raise RuntimeError("药品标签插件需要一个药名")

        brief = str(ctx.get("brief") or "")
        limit = self._pick_int(brief, "limit", 1)
        field = self._pick_str(brief, "field", "")

        record = self._fetch(name, field, limit)
        if record is None:
            raise RuntimeError("openFDA 里没找到这个药：%s（换个通用名试试）" % name)

        flat = self._flatten(record)
        if not flat.get("brand_name") and not flat.get("generic_name"):
            raise RuntimeError("查到了记录，但没有药名/通用名字段，数据可能不完整：%s" % name)

        # text 给下游当"人读摘要"，字段给入库用
        flat["text"] = "%s（%s）：%s" % (
            flat.get("brand_name") or "?",
            flat.get("generic_name") or "?",
            (flat.get("indications") or "无适应症信息")[:120],
        )
        flat["source"] = "openFDA"
        flat["paid"] = False
        return flat

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_int(brief: str, key: str, default: int) -> int:
        m = re.search(r"%s=(\d+)" % re.escape(key), brief or "")
        return int(m.group(1)) if m else default

    @staticmethod
    def _pick_str(brief: str, key: str, default: str) -> str:
        m = re.search(r"%s=([^\s,，;；]+)" % re.escape(key), brief or "")
        return m.group(1) if m else default

    def _fetch(self, name: str, field: str, limit: int) -> Optional[Dict[str, Any]]:
        """查 API。先按指定字段，再按 brand_name / generic_name 兜底。"""
        fields = [field] if field else ["brand_name", "generic_name", "openfda.brand_name", "openfda.generic_name"]
        for f in fields:
            query = '%s:"%s"' % (f, name.replace('"', ""))
            url = "%s?search=%s&limit=%d" % (API, urllib.parse.quote(query, safe='":'), max(1, limit))
            data = self._get_json(url)
            if data and data.get("results"):
                return data["results"][0]
        return None

    @staticmethod
    def _get_json(url: str) -> Optional[Dict[str, Any]]:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None          # 没找到这个药，不是错误
            if exc.code == 429:
                raise RuntimeError("openFDA 限流了，歇几分钟再跑（它默认每分钟 240 次）")
            raise RuntimeError("openFDA 返回 %s：%s" % (exc.code, exc.reason))
        except Exception as exc:
            raise RuntimeError("连不上 openFDA：%s" % exc)

    @staticmethod
    def _flatten(record: Dict[str, Any]) -> Dict[str, Any]:
        """把 openFDA 的嵌套 JSON 压成扁平字段。"""

        def first(v: Any) -> str:
            if isinstance(v, list):
                v = v[0] if v else ""
            return re.sub(r"\s+", " ", str(v or "")).strip()

        openfda = record.get("openfda") or {}
        out: Dict[str, Any] = {
            "brand_name": first(openfda.get("brand_name")) or first(record.get("openfda", {}).get("brand_name")),
            "generic_name": first(openfda.get("generic_name")),
            "manufacturer": first(openfda.get("manufacturer_name")),
            "product_type": first(openfda.get("product_type")),
            "route": ", ".join(openfda.get("route") or [])[:80],
        }

        # 正文段落字段：可能很长，各截一段够用
        def section(key: str, n: int = 400) -> str:
            return first(record.get(key))[:n]

        out["indications"] = section("indications_and_usage")
        out["dosage"] = section("dosage_and_administration")
        out["warnings"] = section("warnings") or section("warnings_and_cautions")
        out["contraindications"] = section("contraindications")

        # 空值转成空串，方便入库
        for k in KEEP_FIELDS:
            out.setdefault(k, "")
        return out


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "aspirin"
    r = OpenFDALabel().execute_rich({"text": name})
    print(json.dumps({k: (str(v)[:80] if v else "") for k, v in r.items()}, ensure_ascii=False, indent=2))
