# -*- coding: utf-8 -*-
"""
结果翻译（b_翻译）
=========================================================================
把检索到的记录在 中文 / 英文 之间转换。

为什么要缓存？
-------------------------------------------------------------------------
    本地模型翻一段要十几秒。同一条记录反复翻译没意义，
    所以用 SQLite 做缓存：同文同语言只算一次。

用法：
    from framework_b import b_翻译
    b_翻译.text("Sepsis, pulmonary", "zh")
    b_翻译.record({"brand_name": ...}, "zh")
=========================================================================
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"

#: 翻译优先用非思考模型：qwen3-vl 每次都要推理十几秒，
#: 翻短词时纯属浪费。按顺序取第一个本机存在的。
TRANSLATE_MODELS = ["qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b", "qwen3-vl:4b"]
MODEL = TRANSLATE_MODELS[-1]      # 实际使用的模型，启动时探测
URL = "http://127.0.0.1:11434/api/generate"
_TAGS_URL = "http://127.0.0.1:11434/api/tags"
_model_picked = False


def _installed() -> list:
    import urllib.request

    try:
        with urllib.request.urlopen(_TAGS_URL, timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


def pick_model() -> str:
    """挑一个可用的翻译模型（带缓存，进程内只探测一次）。"""
    global MODEL, _model_picked
    if _model_picked:
        return MODEL
    have = _installed()
    for name in TRANSLATE_MODELS:
        if name in have:
            MODEL = name
            break
    _model_picked = True
    return MODEL

LANG = {"zh": "中文", "en": "英文"}


def _cache_get(key: str) -> str:
    try:
        conn = sqlite3.connect(str(DB), timeout=30)
        try:
            row = conn.execute("SELECT text FROM translate_cache WHERE h=?", (key,)).fetchone()
            return row[0] if row else ""
        finally:
            conn.close()
    except Exception:
        return ""


def _cache_put(key: str, text: str, target: str) -> None:
    try:
        conn = sqlite3.connect(str(DB), timeout=30)
        conn.execute("CREATE TABLE IF NOT EXISTS translate_cache (h TEXT PRIMARY KEY, target TEXT, text TEXT)")
        conn.execute("INSERT OR REPLACE INTO translate_cache VALUES (?,?,?)", (key, target, text))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _ollama(prompt: str, timeout: int = 180) -> str:
    model = pick_model()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        # think=False 比在提示词里写 /no_think 更可靠：
        # 后者会被模型当成待翻译内容，实测把 "Aspirin" 翻成了 "勿思考"。
        # 非思考模型（qwen2.5）会忽略这个字段，无害。
        "think": False,
        # 非思考模型 400 token 足够；思考模型要多给，否则全花在推理上
        "options": {"temperature": 0.1,
                    "num_predict": 3000 if "vl" in model or "r1" in model else 400,
                    "num_ctx": 4096},
    }
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")).get("response", "")


#: 模型偶尔会把"不要思考"这类标记当成译文吐出来
_JUNK = ("/no_think", "no_think", "不要思考", "勿思考", "只输出译文", "思考")


def _clean(out: str) -> str:
    t = (out or "").strip().strip('"').strip()
    for j in _JUNK:
        t = t.replace(j, "")
    return t.strip(" ：:。.,，")


def text(src: str, target: str = "zh") -> str:
    """翻译一段文本（带缓存）。失败或结果可疑时返回原文，不阻塞页面。"""
    s = str(src or "").strip()
    if not s or len(s) < 2:
        return s
    key = hashlib.sha1(("%s|%s" % (target, s)).encode("utf-8")).hexdigest()
    hit = _cache_get(key)
    # 缓存命中也要做数字校验：里面可能存着旧的坏译文
    if hit and _numbers_ok(s, hit):
        return hit

    if target == "en":
        prompt = "Translate to English, output only the translation: " + s[:1200]
    else:
        prompt = "翻译成中文，只输出译文：" + s[:1200]

    for _attempt in range(2):
        try:
            out = _clean(_ollama(prompt))
        except Exception:
            out = ""
        # 结果校验：空、只剩逗号/数字、或者数字对不上，都当失败重试一次
        if (out and not re.fullmatch(r"[\d\s\-/:.,]*", out)
                and _numbers_ok(s, out)):
            _cache_put(key, out, target)
            return out
    return s


def record(rec: Dict[str, Any], target: str = "zh", fields=None) -> Dict[str, Any]:
    """
    翻译一条记录的字段。

    只翻"像自然语言"的字段：
        * id、时间戳、纯数字、纯英文编码（如 ICD 码）不翻
        * fields 可以显式指定要翻哪些列
    """
    out: Dict[str, Any] = {}
    for k, v in (rec or {}).items():
        if not isinstance(v, str):
            out[k] = v
            continue
        s = v.strip()
        key_low = k.lower()
        # 这些列不翻：主键、各类 ID、时间戳、纯数字/日期
        if (key_low in ("id", "case_id", "set_id", "doc", "h")
                or key_low.endswith("_id")
                or key_low.endswith("time") or key_low.endswith("_at")
                or re.fullmatch(r"[\d\s\-/:.,]+", s)
                or len(s) < 2):
            out[k] = v
            continue
        if fields is not None and k not in fields:
            out[k] = v
            continue
        out[k] = text(v, target)
    return out


#: 模型偶尔会把数字吃掉（实测 "Sodium Chloride 0.9%" → "9%氯化钠"）
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _numbers(s: str) -> set:
    return set(_NUM.findall(str(s or "")))


def _numbers_ok(src: str, dst: str) -> bool:
    """
    译文里的数字必须覆盖原文的数字。

    原文有 0.9，译文只剩 9（或干脆没有），就判定翻译不可信。
    """
    a, b = _numbers(src), _numbers(dst)
    if not a:
        return True
    return a.issubset(b)


_CJK = re.compile(r"[\u4e00-\u9fff]")


def _already_in(src: str, target: str) -> bool:
    """
    判断文本是不是已经是目标语言，是的话直接跳过翻译。

    这一步能省掉大量无意义调用：疾病库里一半以上本来就有中文名，
    送进模型只会白等几十秒。
    """
    s = str(src or "")
    has_cjk = bool(_CJK.search(s))
    if target == "zh":
        # 目标中文：只要含有汉字且没有成句的英文单词，就当已经中文
        latin_words = re.findall(r"[A-Za-z]{3,}", s)
        return has_cjk and len(latin_words) <= 1
    # 目标英文：纯 ASCII 且没有汉字
    return not has_cjk and bool(re.search(r"[A-Za-z]", s))


def preflight(timeout: float = 2.0) -> bool:
    """快速探测本地模型服务是否在线（避免请求挂到超时才报错）。"""
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def batch(names, target: str = "zh") -> Dict[str, str]:
    """
    一次调用翻译一批短词（药名、疾病名）。

    为什么不用 text() 逐个翻？
    -------------------------------------------------------------------
    本地模型每次调用要十几秒，翻 10 个药名就是两分半。
    批量塞进一次请求，输出按行对齐，10 个词也就一次的时间。

    返回 {原文: 译文}；没翻到的、或数字对不上的，原样返回。
    """
    items = [str(x or "").strip() for x in (names or []) if str(x or "").strip()]
    if not items:
        return {}

    out: Dict[str, str] = {}
    todo = []
    for name in items:
        # 已经是目标语言就不翻（最常见的浪费）
        if _already_in(name, target):
            out[name] = name
            continue
        key = hashlib.sha1(("%s|%s" % (target, name)).encode("utf-8")).hexdigest()
        hit = _cache_get(key)
        # 缓存里也可能躺着旧的坏译文（比如数字被吃掉的），命中也要校验
        if hit and _numbers_ok(name, hit):
            out[name] = hit
        else:
            todo.append(name)

    if not todo:
        return out

    def _translate_chunk(chunk, depth: int = 0) -> Dict[str, str]:
        """
        翻一小批。模型经常整批不返回（思考吃光 token），
        所以失败就拆成两半再来，最多拆两层。
        """
        listed = "\n".join("%d. %s" % (i + 1, n) for i, n in enumerate(chunk))
        if target == "en":
            prompt = ("Translate each numbered item into English. "
                      "Keep every number exactly as written (0.9% stays 0.9%). "
                      "Output only the translations, one per line, in the same order, "
                      "no numbering:\n" + listed)
        else:
            prompt = ("把下面每一项翻译成中文。数字必须原样保留（如 0.9% 仍是 0.9%）。\n"
                      "只输出译文，每行一个，顺序一致，不要编号：\n" + listed)

        try:
            raw = _ollama(prompt, timeout=240)
        except Exception:
            raw = ""

        cleaned = []
        for ln in (raw or "").splitlines():
            t = re.sub(r"^\s*\d+[.、)]\s*", "", ln.strip().strip('"').strip())
            if t:
                cleaned.append(t)

        got: Dict[str, str] = {}
        for i, name in enumerate(chunk):
            if i < len(cleaned):
                cand = _clean(cleaned[i])
                if (cand and not re.fullmatch(r"[\d\s\-/:.,]*", cand)
                        and _numbers_ok(name, cand)):
                    got[name] = cand
                    key = hashlib.sha1(("%s|%s" % (target, name)).encode("utf-8")).hexdigest()
                    _cache_put(key, cand, target)

        missing = [n for n in chunk if n not in got]
        # 有漏的就拆半重试（最多两层），比整批重来省时
        if missing and depth < 2 and len(chunk) > 2:
            mid = len(chunk) // 2
            for half in (chunk[:mid], chunk[mid:]):
                got.update({k: v for k, v in _translate_chunk(half, depth + 1).items()
                            if k not in got})
        return got

    for i in range(0, len(todo), 8):
        chunk = todo[i:i + 8]
        out.update(_translate_chunk(chunk))

    # 仍然没翻到的，保留原文（宁可显示原文，也不给错译）
    for name in todo:
        out.setdefault(name, name)
    return out


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法：python framework_b\\b_翻译.py <文本> [zh|en]")
        sys.exit(0)
    print(text(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "zh"))
