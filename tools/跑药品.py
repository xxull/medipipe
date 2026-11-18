# -*- coding: utf-8 -*-
"""
批量采集药品标签（openFDA 分页）
=========================================================================
用法
-------------------------------------------------------------------------
    python tools/跑药品.py                # 默认拉 500 条
    python tools/跑药品.py 2000           # 拉 2000 条
    python tools/跑药品.py 2000 5000      # 从第 5000 条开始拉 2000 条

为什么不用"一个药名一次请求"？
-------------------------------------------------------------------------
    openFDA 支持 limit=100 的分页：一次请求拿 100 个药品标签。
    按药名查要请求上百次，分页只要 1 次 —— 快 100 倍，也不容易触发限流。

去重
-------------------------------------------------------------------------
    用 openFDA 的 set_id（同一份说明书唯一）做去重键；
    没有 set_id 的，用 药名+厂商 的哈希。

限流
-------------------------------------------------------------------------
    不填 Key 时：每分钟约 240 次请求。脚本每页之间 sleep 0.5 秒，
    1000 条 = 10 次请求 ≈ 5 秒，远低于限制。
=========================================================================
"""

import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

API = "https://api.fda.gov/drug/label.json"
PAGE = 100                 # 每页条数（openFDA 上限 100）
DB = ROOT / "data" / "records.db"
TABLE = "drugs"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}

COLUMNS = [
    "set_id", "brand_name", "generic_name", "manufacturer", "product_type",
    "route", "indications", "dosage", "warnings", "contraindications", "effective_time",
]


def fetch_page(skip: int, limit: int = PAGE, retries: int = 3) -> dict:
    """取一页。被限流就等一分钟再试（最多 retries 次）。"""
    url = "%s?limit=%d&skip=%d" % (API, limit, skip)
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, headers=UA)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {"results": []}      # skip 超过总数
            if exc.code == 429:
                wait = 60 if attempt < retries else 120
                print("  被限流，等 %d 秒后重试（第 %d/%d 次）" % (wait, attempt, retries))
                time.sleep(wait)
                continue
            if 500 <= exc.code < 600:
                wait = 10 * attempt
                print("  服务器 %s，等 %d 秒重试" % (exc.code, wait))
                time.sleep(wait)
                continue
            raise RuntimeError("openFDA 返回 %s：%s" % (exc.code, exc.reason))
        except Exception as exc:
            if attempt >= retries:
                raise RuntimeError("连不上 openFDA：%s" % exc)
            time.sleep(5 * attempt)
    raise RuntimeError("重试 %d 次仍然失败：%s" % (retries, url))


def clean_name(raw: str) -> str:
    """把药名里的说明性前缀清掉，只留干净的名字。"""
    s = re.sub(r"\s+", " ", str(raw or "")).strip()
    s = re.sub(r"(?i)^\(?in each[^)]*\)?\s*", "", s)          # (in each tablet)
    s = re.sub(r"(?i)^(active\s+ingredients?|drug\s+facts)\s*[:：]?\s*", "", s)
    s = re.sub(r"(?i)^purpose\s*[:：]?\s*", "", s)             # Purpose Antiseptic
    s = re.sub(r"^[\s·•\-—:：,，]+", "", s)
    return s[:80].strip()


def flatten(rec: dict) -> dict:
    """把 openFDA 记录压成一行。逻辑和插件里的保持一致。"""
    def first(v):
        if isinstance(v, list):
            v = v[0] if v else ""
        return re.sub(r"\s+", " ", str(v or "")).strip()

    openfda = rec.get("openfda") or {}

    # openfda 块为空时（实测约 2/3 的老标签是这样），
    # 药名只能从其它字段里找：spl_product_data_elements / active_ingredient / purpose
    def alt_names():
        brand = first(openfda.get("brand_name"))
        generic = first(openfda.get("generic_name"))
        prod = first(openfda.get("product_type"))
        route = ", ".join(openfda.get("route") or [])[:80]

        if not brand:
            spl = rec.get("spl_product_data_elements")
            if isinstance(spl, list) and spl:
                brand = re.sub(r"\s+", " ", str(spl[0])).strip()[:80]
        if not generic:
            act = rec.get("active_ingredient")
            if isinstance(act, list) and act:
                raw = re.sub(r"\s+", " ", str(act[0])).strip()
                # 去掉 "ACTIVE INGREDIENTS:" 这类前缀
                raw = re.sub(r"(?i)^(active\s+ingredients?|drug\s+facts)\s*[:：]?\s*", "", raw)
                generic = raw[:80]
        if not prod:
            prod = first(rec.get("purpose"))[:60]
        return brand, generic, prod, route

    alt_brand, alt_generic, alt_type, alt_route = alt_names()
    return {
        "set_id": first(rec.get("set_id")) or first(openfda.get("spl_set_id")),
        "brand_name": clean_name(alt_brand),
        "generic_name": clean_name(alt_generic),
        "manufacturer": first(openfda.get("manufacturer_name")),
        "product_type": alt_type,
        "route": alt_route,
        "indications": first(rec.get("indications_and_usage"))[:400],
        "dosage": first(rec.get("dosage_and_administration"))[:400],
        "warnings": (first(rec.get("warnings")) or first(rec.get("warnings_and_cautions")))[:400],
        "contraindications": first(rec.get("contraindications"))[:400],
        "effective_time": first(rec.get("effective_time")),
    }


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        'CREATE TABLE IF NOT EXISTS "%s" ('
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " set_id TEXT,"
        " brand_name TEXT, generic_name TEXT, manufacturer TEXT, product_type TEXT,"
        " route TEXT, indications TEXT, dosage TEXT, warnings TEXT,"
        " contraindications TEXT, effective_time TEXT,"
        " created_at TEXT)" % TABLE
    )
    # 老表升级：之前入库插件建的表没有 set_id，补上
    cols = {r[1] for r in conn.execute('PRAGMA table_info("%s")' % TABLE)}
    for c in COLUMNS:
        if c not in cols:
            conn.execute('ALTER TABLE "%s" ADD COLUMN "%s" TEXT' % (TABLE, c))
    # 去重靠唯一索引（ALTER 加不了 UNIQUE，只能建索引）
    conn.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS idx_%s_setid ON "%s"(set_id)' % (TABLE, TABLE)
    )
    conn.commit()


def main() -> int:
    total = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    start = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB), timeout=30)
    ensure_table(conn)

    inserted = skipped = errors = 0
    skip = start
    t0 = time.time()

    while inserted + skipped < total:
        try:
            data = fetch_page(skip)
        except RuntimeError as exc:
            print("取数失败：", exc)
            errors += 1
            break

        results = data.get("results") or []
        if not results:
            print("没有更多数据了（skip=%d）" % skip)
            break

        rows = []
        for rec in results:
            row = flatten(rec)
            if not row["set_id"]:
                # 没有唯一键就用内容 hash，避免重复插
                key = "%s|%s|%s" % (row["generic_name"], row["brand_name"], row["manufacturer"])
                row["set_id"] = "h_" + str(abs(hash(key)))[:16]
            rows.append(row)

        for row in rows:
            cur = conn.execute(
                'INSERT OR IGNORE INTO "%s" (%s, created_at) VALUES (%s)'
                % (TABLE, ",".join('"%s"' % c for c in COLUMNS), ",".join("?" * (len(COLUMNS) + 1))),
                [row[c] for c in COLUMNS] + [time.strftime("%Y-%m-%d %H:%M:%S")],
            )
            if cur.rowcount:
                inserted += 1
            else:
                skipped += 1
        conn.commit()

        skip += PAGE
        n_total = conn.execute('SELECT COUNT(*) FROM "%s"' % TABLE).fetchone()[0]
        print("skip=%-6d 本页 %d 条 | 新增 %d，重复 %d | 库里共 %d 条 | %.1fs"
              % (skip - PAGE, len(results), inserted, skipped, n_total, time.time() - t0))
        time.sleep(0.5)

    n_total = conn.execute('SELECT COUNT(*) FROM "%s"' % TABLE).fetchone()[0]
    conn.close()
    print("\n完成：新增 %d，重复 %d，失败 %d 次；库里共 %d 条；用时 %.1f 秒"
          % (inserted, skipped, errors, n_total, time.time() - t0))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
