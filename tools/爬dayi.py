# -*- coding: utf-8 -*-
"""
抓取 dayi.org.cn（中国医药信息查询平台）的公开词条
=========================================================================
为什么用这个源？
-------------------------------------------------------------------------
    * robots.txt 明确允许（`Disallow:` 为空）
    * 有 sitemap，页面可枚举
    * 服务端渲染，HTML 里就有正文，不用浏览器
    * 内容经"国家中医药管理局名词术语"项目审核

抓什么
-------------------------------------------------------------------------
    drug         药品说明书（约 3 万）
    symptom      症状（约 4 千）
    disease      疾病
    qa           问答
    prescriptions 方剂
    term         名词术语

怎么存
-------------------------------------------------------------------------
    data/records.db → 表 dayi_pages
        url    主键（重复抓会跳过，天然支持断点续传）
        type   类型
        title  标题
        text   正文（整段，供全文索引）
        fields 抽取到的关键字段（JSON）
        ts     抓取时间

用法
-------------------------------------------------------------------------
    python tools\爬dayi.py --types drug --limit 20     先抓 20 条看质量
    python tools\爬dayi.py --types all                 全量（很久）
=========================================================================
"""
import argparse
import json
import re
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"
BASE = "https://www.dayi.org.cn"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0"}

#: sitemap 里的目录名 → 我们的类型名
TYPES = {
    "drug": "drug",
    "symptom": "symptom",
    "disease": "disease",
    "qa": "qa",
    "prescriptions": "prescriptions",
    "term": "term",
    "surgery": "surgery",
    "cmedical": "cmedical",
}

#: 药品页常见字段（出现就抽出来）
FIELDS = ["成分", "适应症", "功能主治", "用法用量", "不良反应", "禁忌",
          "注意事项", "规格", "贮藏", "有效期", "批准文号", "生产企业"]


def ensure(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dayi_pages ("
        " url TEXT PRIMARY KEY, type TEXT, title TEXT, text TEXT,"
        " fields TEXT, ts TEXT)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dayi_type ON dayi_pages(type)")
    conn.commit()


def list_sitemaps() -> dict:
    """返回 {类型: [子 sitemap 地址]}"""
    r = requests.get(BASE + "/sitemap.xml", headers=UA, timeout=30)
    locs = re.findall(r"<loc>(.*?)</loc>", r.text)
    out = {}
    for u in locs:
        m = re.search(r"/prd/pc/([^/]+)/", u)
        if not m:
            continue
        kind = m.group(1)
        if kind in TYPES or kind in ("a_article", "article"):
            out.setdefault(kind, []).append(u)
    return out


def urls_of(sitemap_url: str, cap: int = 0) -> list:
    try:
        r = requests.get(sitemap_url, headers=UA, timeout=30)
        urls = re.findall(r"<loc>(.*?)</loc>", r.text)
        return urls[:cap] if cap else urls
    except Exception:
        return []


def parse_page(url: str) -> dict:
    """
    抓一页并抽正文 + 字段。

    页面结构（实测）：
        <div class="article-detail-container">
            <h1>健脑丸（处方药）</h1>
            ...
            <h2>成分</h2><div>当归、天竺黄…</div>
            <h2>用法用量</h2><div>口服。一次…</div>
        </div>

    所以按 h2 逐段取下一个兄弟节点，比在原文本上跑正则可靠得多
    （正则那版把导航栏当成了正文）。
    """
    r = _session().get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    box = soup.select_one(".article-detail-container") or soup
    h1 = box.find("h1")
    title = h1.get_text(strip=True) if h1 else (
        soup.title.get_text(strip=True) if soup.title else "")

    fields = {}
    # h2 外面裹了一层 div（class="flex items-center"），内容在**这层 div 的后续兄弟**里。
    # 所以先把标题包到"只含标题的那层"，再往后收集兄弟节点，直到遇到下一个标题。
    for h in box.find_all(["h2", "h3"]):
        name = h.get_text(strip=True).strip("：:")
        if not name or len(name) > 20:
            continue
        holder = h
        while (holder.parent is not None
               and len(holder.parent.get_text(strip=True)) <= len(name) + 4):
            holder = holder.parent

        parts = []
        for sib in holder.next_siblings:
            try:
                if sib.find and sib.find(["h2", "h3"]):
                    break
                seg = sib.get_text(" ", strip=True) if hasattr(sib, "get_text") else str(sib).strip()
            except Exception:
                continue
            if seg:
                parts.append(re.sub(r"\s+", " ", seg))
            if len(" ".join(parts)) > 1200:
                break
        val = " ".join(parts).strip(" ：:，,。")
        if val:
            fields[name] = val[:1200]

    text = re.sub(r"\s+", " ", box.get_text(" ", strip=True))
    text = re.sub(r"^.*?审核认证", "", text).strip() or text

    return {"title": title[:200], "text": text[:8000], "fields": fields}


#: 每个线程一个 Session（复用 TCP 连接，比每次新建快 3-5 倍）
_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(UA)
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=8,
                                               max_retries=2)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _local.s = s
    return s


def fetch_one(url: str, delay: float = 0.1) -> dict:
    """在线程里跑：小睡一下（错峰）+ 抓取解析。"""
    if delay:
        time.sleep(delay)
    return parse_page(url)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--types", default="drug",
                    help="逗号分隔，或 all（drug,symptom,disease,qa,prescriptions,term）")
    ap.add_argument("--limit", type=int, default=0, help="每个类型最多抓多少条")
    ap.add_argument("--delay", type=float, default=0.1, help="每个请求前的等待（秒）")
    ap.add_argument("--threads", type=int, default=8, help="并发线程数")
    args = ap.parse_args()

    wanted = list(TYPES) if args.types == "all" else [
        x.strip() for x in args.types.split(",") if x.strip()
    ]

    maps = list_sitemaps()
    print("sitemap 类型:", {k: len(v) for k, v in maps.items()}, flush=True)

    conn = sqlite3.connect(str(DB), timeout=120)
    ensure(conn)

    t0 = time.time()
    total_new = 0

    for kind in wanted:
        if kind not in maps:
            print("跳过（没有 sitemap）:", kind, flush=True)
            continue
        urls = []
        for sm in maps[kind]:
            urls += urls_of(sm)
            if args.limit and len(urls) >= args.limit:
                break
        if args.limit:
            urls = urls[: args.limit]

        # 断点续跑：先剔掉已经抓过的
        done = {r[0] for r in conn.execute(
            "SELECT url FROM dayi_pages WHERE type=?", (TYPES.get(kind, kind),))}
        todo = [u for u in urls if u not in done]
        print("\n== %s：总 %d，已完成 %d，待抓 %d，并发 %d"
              % (kind, len(urls), len(done), len(todo), args.threads), flush=True)

        buf = []
        with ThreadPoolExecutor(max_workers=args.threads) as pool:
            futures = {pool.submit(fetch_one, u, args.delay): u for u in todo}
            for i, fut in enumerate(as_completed(futures), start=1):
                url = futures[fut]
                try:
                    page = fut.result()
                except Exception:
                    continue
                buf.append((url, TYPES.get(kind, kind), page["title"], page["text"],
                            json.dumps(page["fields"], ensure_ascii=False),
                            time.strftime("%Y-%m-%d %H:%M:%S")))
                if len(buf) >= 50:
                    conn.executemany(
                        "INSERT OR REPLACE INTO dayi_pages VALUES (?,?,?,?,?,?)", buf)
                    conn.commit()
                    total_new += len(buf)
                    buf.clear()
                if i % 200 == 0:
                    rate = i / max(1e-9, time.time() - t0)
                    left = (len(todo) - i) / max(0.1, rate) / 60
                    print("  %d/%d  %.1f 条/秒  预计还要 %.0f 分钟"
                          % (i, len(todo), rate, left), flush=True)
        if buf:
            conn.executemany("INSERT OR REPLACE INTO dayi_pages VALUES (?,?,?,?,?,?)", buf)
            conn.commit()
            total_new += len(buf)

    n = conn.execute("SELECT COUNT(*) FROM dayi_pages").fetchone()[0]
    size = DB.stat().st_size / 1024 ** 2
    conn.close()
    print("\n完成：本次新增 %d，表内共 %d 条，用时 %.0f 秒，库 %.0f MB"
          % (total_new, n, time.time() - t0, size), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
