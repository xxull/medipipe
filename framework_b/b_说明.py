# -*- coding: utf-8 -*-
"""
词条说明（b_说明）
=========================================================================
点疾病/药物名时，给它一段说明：

    药物 → 优先中文说明书（dayi，含适应症/用法/禁忌），退回 openFDA
    疾病 → 优先 dayi 疾病词条，退回病例库里的诊断名上下文

为什么不直接内嵌到界面里？
-------------------------------------------------------------------------
    说明的取数逻辑以后会变（比如加医保目录、加相互作用），
    抽成一个模块，界面只负责"点了就展示"。
=========================================================================
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Dict

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"

#: 药品说明书里优先展示的字段顺序
DRUG_KEYS = ["适应症", "适应病症", "功能主治", "用法用量", "不良反应", "禁忌", "注意事项"]


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def drug(name: str) -> Dict:
    """
    药名 → 说明书要点。先查中文（dayi），再查 openFDA。
    """
    n = _clean(name)
    if not n:
        return {}
    conn = sqlite3.connect(str(DB), timeout=60)
    try:
        row = conn.execute(
            "SELECT title, url, fields, text FROM dayi_pages"
            " WHERE type='drug' AND (title LIKE ? OR title=?) LIMIT 1",
            ("%" + n + "%", n),
        ).fetchone()
        if row:
            title, url, fields_json, text = row
            try:
                f = json.loads(fields_json or "{}")
            except Exception:
                f = {}
            picked = {k: f[k] for k in DRUG_KEYS if f.get(k)}
            return {
                "名称": title,
                "来源": "中国医药信息查询平台",
                "类型": f.get("药品类型") or f.get("处方类型") or "",
                "要点": picked or {"说明": (text or "")[:400]},
                "链接": url,
            }

        row = conn.execute(
            "SELECT brand_name, generic_name, indications, dosage, warnings, manufacturer"
            " FROM drugs WHERE brand_name=? OR generic_name=? LIMIT 1", (n, n)
        ).fetchone()
        if row:
            return {
                "名称": row[0] or row[1],
                "来源": "openFDA（英文）",
                "类型": "处方药/OTC",
                "要点": {
                    "适应症": (row[2] or "")[:400],
                    "用法用量": (row[3] or "")[:300],
                    "警告": (row[4] or "")[:300],
                    "厂商": row[5] or "",
                },
            }
        return {}
    finally:
        conn.close()


def disease(name: str) -> Dict:
    """病名 → 说明。先查 dayi 疾病词条，再退回病例库中的诊断上下文。"""
    n = _clean(name)
    if not n:
        return {}
    conn = sqlite3.connect(str(DB), timeout=60)
    try:
        row = conn.execute(
            "SELECT title, url, text FROM dayi_pages WHERE type='disease' AND title LIKE ? LIMIT 1",
            ("%" + n + "%",),
        ).fetchone()
        if row:
            return {
                "名称": row[0],
                "来源": "中国医药信息查询平台",
                "要点": {"概述": (row[2] or "")[:500]},
                "链接": row[1],
            }

        # 退回：看看病例库里这个病名出现在多少病例里
        cnt = conn.execute(
            "SELECT COUNT(*) FROM case_corpus WHERE diseases LIKE ?", ("%" + n + "%",)
        ).fetchone()[0]
        if cnt:
            return {
                "名称": n,
                "来源": "病例库",
                "要点": {"出现次数": "%d 个病例含此诊断" % cnt},
            }
        return {}
    finally:
        conn.close()
