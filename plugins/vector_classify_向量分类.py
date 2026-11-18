# -*- coding: utf-8 -*-
"""
向量分类插件（vector_classify_向量分类）
=========================================================================
用本地嵌入模型，把一段文本归到一个标签上。标签由**节点备注**自己给，
框架不预设任何行业标签。

怎么用
-------------------------------------------------------------------------
在节点的「备注」里写：

    labels=新闻,广告,教程        # 逗号/顿号/空格分隔都行
    model=bge-m3:latest          # 可选，默认 bge-m3
    min=0.45                     # 可选，低于这个相似度就返回"不确定"

输出
-------------------------------------------------------------------------
    {"label": "教程", "score": 0.62, "uncertain": false,
     "labels": ["新闻","广告","教程"], "method": "embedding"}

原理
-------------------------------------------------------------------------
    1. 把每个标签算一个向量（缓存到 data/vector_labels_<hash>.json，不重复算）
    2. 把输入文本算一个向量
    3. 余弦相似度最高的那个标签就是结果

为什么不用关键词匹配？
-------------------------------------------------------------------------
    关键词匹配换个说法就失效；向量比的是"意思像不像"，
    "怎么装这个库" 和 "安装步骤" 能被认成同一类。
=========================================================================
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import urllib.request
from typing import Any, Dict, List

from base_基类 import BasePlugin

DEFAULT_MODEL = "bge-m3:latest"
DEFAULT_MIN = 0.45
MAX_LABELS = 30


class VectorClassify(BasePlugin):
    """向量相似度分类。"""

    name = "向量分类"
    NEEDS = {"network": False, "model": True}
    OUTPUT_FIELDS = ["label", "score"]

    # ------------------------------------------------------------------
    def execute(self, text_data: str) -> str:
        result = self.execute_rich({"text": text_data, "brief": ""})
        return str(result.get("label", ""))

    def execute_rich(self, ctx: dict) -> Dict[str, Any]:
        text = str(ctx.get("original") or ctx.get("text") or "").strip()
        if not text:
            raise RuntimeError("向量分类收到空文本")

        brief = str(ctx.get("brief") or "")
        labels = self._parse_labels(brief)
        if not labels:
            raise RuntimeError(
                "没给标签。在节点备注里写：labels=标签A,标签B,标签C"
            )

        model = self._pick(brief, "model", DEFAULT_MODEL)
        threshold = float(self._pick(brief, "min", DEFAULT_MIN))

        base = self._ollama_base()
        vec = self._embed(base, model, text[:4000])

        best_label, best_score = "", -1.0
        for label, lvec in zip(labels, self._label_vectors(base, model, labels)):
            score = self._cosine(vec, lvec)
            if score > best_score:
                best_label, best_score = label, score

        uncertain = best_score < threshold
        return {
            "label": "不确定" if uncertain else best_label,
            "best_guess": best_label,
            "score": round(best_score, 4),
            "threshold": threshold,
            "uncertain": uncertain,
            "labels": labels,
            "method": "embedding",
            "model": model,
            "paid": False,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _pick(brief: str, key: str, default: Any) -> Any:
        m = re.search(r"%s=([^\s,，;；]+)" % re.escape(key), brief or "")
        return m.group(1) if m else default

    @staticmethod
    def _parse_labels(brief: str) -> List[str]:
        """从备注里抠 labels=... ，支持逗号/顿号/空格/竖线分隔。"""
        m = re.search(r"labels=([^\n]+)", brief or "")
        if not m:
            return []
        raw = m.group(1)
        # 去掉可能跟在后面的其它参数
        raw = re.split(r"\s+(?:model|min)=", raw)[0]
        parts = re.split(r"[,，、;；|/\s]+", raw)
        out = []
        for p in parts:
            p = p.strip(" \"'")
            if p and p not in out:
                out.append(p)
        return out[:MAX_LABELS]

    @staticmethod
    def _ollama_base() -> str:
        try:
            from core.launcher_服务启动 import OLLAMA_BASE, ensure_ollama

            ok, msg = ensure_ollama(True)
            if not ok:
                raise RuntimeError("本地模型服务没起来：%s" % msg)
            return OLLAMA_BASE
        except ImportError:
            return "http://127.0.0.1:11434"
        except RuntimeError:
            raise

    @staticmethod
    def _embed(base: str, model: str, text: str) -> List[float]:
        """调 Ollama 的 /api/embeddings 拿向量。"""
        payload = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            base + "/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(
                "拿不到向量（模型 %s 装了吗？Ollama 在跑吗）：%s" % (model, exc)
            )
        vec = data.get("embedding") or []
        if not vec:
            raise RuntimeError("模型返回的向量是空的")
        return [float(x) for x in vec]

    def _label_vectors(self, base: str, model: str, labels: List[str]) -> List[List[float]]:
        """标签向量带缓存：同样一组标签只算一次。"""
        key = hashlib.sha1(("%s|%s" % (model, "|".join(labels))).encode("utf-8")).hexdigest()[:16]
        cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
        cache_path = os.path.join(cache_dir, "vector_labels_%s.json" % key)

        try:
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as fp:
                    cached = json.load(fp)
                if isinstance(cached, dict) and all(x in cached for x in labels):
                    return [cached[x] for x in labels]
        except Exception:
            pass

        vectors = [self._embed(base, model, x) for x in labels]

        try:
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as fp:
                json.dump(dict(zip(labels, vectors)), fp)
        except Exception:
            pass
        return vectors

    @staticmethod
    def _cosine(a: List[float], b: List[float]) -> float:
        if not a or not b or len(a) != len(b):
            return -1.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return -1.0
        return dot / (na * nb)


if __name__ == "__main__":
    import sys

    text = sys.argv[1] if len(sys.argv) > 1 else "怎么安装这个 Python 库"
    brief = sys.argv[2] if len(sys.argv) > 2 else "labels=新闻,广告,教程"
    r = VectorClassify().execute_rich({"text": text, "brief": brief})
    print(json.dumps(r, ensure_ascii=False, indent=2))
