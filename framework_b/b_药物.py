# -*- coding: utf-8 -*-
"""
药物推荐（b_药物）
=========================================================================
两个来源，互补：
    ① 病例库：相似病例里实际用过的药（有统计意义，但只覆盖有记录的病例）
    ② 药品库：按适应症文本匹配（即使没有病例，也能告诉你"这个病一般用什么药"）

用法：
    from framework_b import b_药物
    b_药物.for_diseases(["胃癌", "Gastric cancer"])
=========================================================================
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"


def _clean(w: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff\- ]", "", (w or "").strip())


def has_zh_labels() -> bool:
    """库里有中文药品说明书吗？（公开版没有，只有 openFDA 英文数据）"""
    conn = sqlite3.connect(str(DB), timeout=30)
    try:
        return bool(conn.execute(
            "SELECT 1 FROM dayi_pages WHERE type='drug' LIMIT 1").fetchone())
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def for_disease_zh(name: str, limit: int = 8) -> List[Dict]:
    """
    在中文药品说明书（dayi）里按病名找药。

    匹配的是「适应症 / 适应病症 / 功能主治」字段，比 openFDA 的英文文本更贴中文提问。
    返回 [{"药物", "适应症", "类型", "链接"}]
    """
    kw = _clean(name)
    if len(kw) < 2:
        return []
    conn = sqlite3.connect(str(DB), timeout=60)
    try:
        # 先粗筛（SQL LIKE），多取一些再精筛（只在适应症里判定）。
        # 只取 limit*3 会抽到一堆"正文提到但适应症没提"的，命中率很低。
        try:
            rows = conn.execute(
                "SELECT title, url, fields FROM dayi_pages"
                " WHERE type='drug' AND (fields LIKE ? OR title LIKE ?)"
                " LIMIT ?",
                ("%%%s%%" % kw, "%%%s%%" % kw, max(300, limit * 30)),
            ).fetchall()
        except sqlite3.Error:
            rows = []      # 公开版没有 dayi 表，直接走 openFDA
    finally:
        conn.close()

    out = []
    for title, url, fields_json in rows:
        try:
            f = json.loads(fields_json or "{}")
        except Exception:
            f = {}
        # 只在**适应症**里判定，别用全文匹配：
        # 说明书正文常出现"高血压患者慎用"，那不算治高血压。
        ind = (f.get("适应症") or f.get("适应病症") or f.get("功能主治") or "")
        if kw not in ind:
            continue
        out.append({
            "药物": (title or "")[:60],
            "适应症": ind[:200],
            "类型": f.get("药品类型") or f.get("处方类型") or "",
            "链接": url,
        })
        if len(out) >= limit:
            break
    return out


def for_diseases(names: List[str], limit: int = 5) -> List[Dict]:
    """
    按疾病名在药品库里找可能的治疗药物。

    返回 [{"药物", "通用名", "适应症片段", "质量分"}]

    说明：这是**文本匹配**，不是药理判断。命中的依据是说明书里出现了病名，
    只作参考，不能当处方。
    """
    if not names:
        return []
    conn = sqlite3.connect(str(DB), timeout=60)
    out: List[Dict] = []
    seen = set()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(drugs)")}
        if not cols:
            return []
        has_q = "quality" in cols
        sel = "brand_name, generic_name, indications, %s" % ("quality" if has_q else "NULL")
        for name in names[:4]:
            kw = _clean(name)
            if len(kw) < 2:
                continue
            rows = conn.execute(
                "SELECT %s FROM drugs"
                " WHERE indications LIKE ? OR brand_name LIKE ? OR generic_name LIKE ?"
                " ORDER BY %s DESC LIMIT ?"
                % (sel, "IFNULL(quality,0)" if has_q else "id"),
                ("%%%s%%" % kw, "%%%s%%" % kw, "%%%s%%" % kw, limit),
            ).fetchall()
            for brand, generic, ind, q in rows:
                key = (brand or generic or "").lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append({
                    "匹配疾病": name,
                    "药物": (brand or "")[:60],
                    "通用名": (generic or "")[:40],
                    "适应症片段": (ind or "")[:160],
                    "质量分": q or 0,
                })
    finally:
        conn.close()
    return out[:12]


#: drug_info 需要的列（库里可能是别的工具建的表，缺列要能兜住）
_INFO_COLS = ["brand_name", "generic_name", "manufacturer", "indications",
              "dosage", "warnings", "contraindications", "route",
              "product_type", "quality"]


def drug_info(name: str) -> Dict:
    """
    查单个药的详情（说明书要点）。

    注意：`drugs` 表可能是不同脚本建的（跑药品.py / 导入开放数据.py / 入库插件），
    列不一定齐全。以前这里写死一串列名，公开版就报 no such column，
    现在按实际列拼 SQL，缺的列给空值。
    """
    conn = sqlite3.connect(str(DB), timeout=60)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(drugs)")}
        if not cols:
            return {}
        use = [c for c in _INFO_COLS if c in cols]
        row = conn.execute(
            "SELECT %s FROM drugs WHERE brand_name=? OR generic_name=? LIMIT 1"
            % ", ".join(use), (name, name),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    out = dict.fromkeys(_INFO_COLS, "")
    out.update(dict(zip(use, row)))
    return out
