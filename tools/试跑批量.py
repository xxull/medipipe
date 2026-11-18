# -*- coding: utf-8 -*-
"""
小批量试跑：多个网页 → 抓取 → 抽取 → 入库。

用途：正式铺量之前，先用几条确认链路通、字段齐、库在长。
    python tools/试跑批量.py                # 用默认几条公开网页
    python tools/试跑批量.py urls.txt       # 一行一个网址
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "plugins"))

from core.loader_模块加载 import load  # noqa: E402

engine = load("core/engine_执行引擎.py", "try_engine")
loader = load("core/plugins_加载实例.py", "try_loader")

PLUGINS = {
    "web_scraper": str(ROOT / "plugins" / "web_scraper_网页抓取.py"),
    "ai_extractor": str(ROOT / "plugins" / "ai_extractor_字段抽取.py"),
    "db_writer": str(ROOT / "plugins" / "db_writer_入库.py"),
}

WORKFLOW = [
    {"step": "s1", "key": "web_scraper", "name": "抓取", "kind": "plugin",
     "brief": "抓网页正文", "order": 1, "parallel_group": ""},
    {"step": "s2", "key": "ai_extractor", "name": "抽取", "kind": "plugin",
     "brief": "抽 title/summary/keywords", "order": 2, "parallel_group": ""},
    {"step": "s3", "key": "db_writer", "name": "入库", "kind": "plugin",
     "brief": "", "order": 3, "parallel_group": ""},
]

DEFAULT_URLS = [
    "https://example.com",
    "https://www.python.org/about/",
    "https://docs.python.org/3/library/json.html",
    "https://news.ycombinator.com/",
]


def main() -> int:
    if len(sys.argv) > 1:
        urls = [x.strip() for x in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if x.strip()]
    else:
        urls = DEFAULT_URLS

    instances = loader.load_instances(PLUGINS)
    print("加载插件：%s\n" % "、".join(sorted(instances)))

    ok_cnt = 0
    started = time.time()

    for i, url in enumerate(urls, start=1):
        print("=" * 70)
        print("[%d/%d] %s" % (i, len(urls), url))
        report = engine.run_workflow(
            WORKFLOW, plugins=instances, master=None, input_text=url,
            logger=lambda m: print("   " + m), step_timeout=60,
        )
        if report["ok"]:
            ok_cnt += 1
        print("    → %s，%d ms" % ("成功" if report["ok"] else "失败", report["ms"]))

    # 看库
    import sqlite3

    db = ROOT / "data" / "records.db"
    print("\n" + "=" * 70)
    if db.exists():
        conn = sqlite3.connect(str(db))
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for t in tables:
                n = conn.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
                print("表 %-12s %d 条" % (t, n))
            for row in conn.execute('SELECT id, title, source FROM records ORDER BY id DESC LIMIT 4'):
                print("  →", [str(x)[:50] for x in row])
        finally:
            conn.close()
    else:
        print("库还没生成")

    print("\n成功 %d / %d，总用时 %.1f 秒" % (ok_cnt, len(urls), time.time() - started))
    return 0 if ok_cnt == len(urls) else 1


if __name__ == "__main__":
    sys.exit(main())
