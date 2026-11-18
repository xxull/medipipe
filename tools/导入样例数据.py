# -*- coding: utf-8 -*-
"""
导入样例数据（让仓库克隆下来就能跑）
=========================================================================
做的事情
-------------------------------------------------------------------------
    1. 把 data/样例数据/病例样例.jsonl 写进 case_corpus（source='sample'）
    2. 顺手把它们塞进全文索引（关键词检索能搜到）
    3. 给这 204 条建向量（bge-m3，约 20 秒）
    4. 打印结果，告诉你可以打开 B 了

用法
-------------------------------------------------------------------------
    python tools\导入样例数据.py
=========================================================================
"""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b.b_分词 import to_index_text  # noqa: E402

DB = ROOT / "data" / "records.db"
SAMPLE = ROOT / "data" / "样例数据" / "病例样例.jsonl"


def main() -> int:
    if not SAMPLE.exists():
        print("找不到样例文件：%s" % SAMPLE)
        print("先跑 python tools\\生成样例数据.py")
        return 1

    rows = [json.loads(x) for x in SAMPLE.read_text(encoding="utf-8").splitlines() if x.strip()]
    print("样例病例：%d 条" % len(rows))

    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB), timeout=120)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS case_corpus ("
        " case_id TEXT PRIMARY KEY, source TEXT, text TEXT,"
        " diseases TEXT, drugs TEXT, created_at TEXT)"
    )
    # 老库可能缺列，补齐
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_corpus)")}
    for col, typ in (("dept", "TEXT"), ("age", "INTEGER"), ("age_band", "TEXT")):
        if col not in cols:
            conn.execute("ALTER TABLE case_corpus ADD COLUMN %s %s" % (col, typ))

    conn.execute("DELETE FROM case_corpus WHERE source='sample'")
    conn.executemany(
        "INSERT OR REPLACE INTO case_corpus"
        " (case_id, source, text, diseases, drugs, created_at, dept, age, age_band)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (r["case_id"], "sample", r["text"],
             json.dumps(r["diseases"], ensure_ascii=False),
             json.dumps(r["drugs"], ensure_ascii=False),
             time.strftime("%Y-%m-%d %H:%M:%S"),
             r["dept"], r["age"], r["age_band"])
            for r in rows
        ],
    )
    conn.commit()
    print("已写入 case_corpus（source=sample）")

    # 顺手把病例写进全文索引，这样「关键词检索」不用退回 LIKE 全表扫
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
        " body, src UNINDEXED, doc UNINDEXED, tokenize='unicode61')"
    )
    conn.execute("DELETE FROM search_fts WHERE src='case_corpus'")
    buf = []
    for cid, text in conn.execute("SELECT case_id, text FROM case_corpus WHERE source='sample'"):
        body = to_index_text(str(text or "")[:4000])
        if body:
            buf.append((body, "case_corpus", cid))
    conn.executemany("INSERT INTO search_fts(body, src, doc) VALUES (?,?,?)", buf)
    conn.commit()
    print("已建全文索引：%d 条" % len(buf))
    conn.close()

    print("\n开始建向量（204 条，约 20 秒）…")
    rc = subprocess.run([sys.executable, "-u", str(ROOT / "tools" / "建向量.py")], cwd=str(ROOT)).returncode
    if rc != 0:
        print("建向量失败（返回 %d）。可稍后手动跑：python tools\\建向量.py" % rc)
        return rc

    print("\n完成。启动 B：")
    print("  python -m streamlit run framework_b/app_b.py --server.port=8502")
    print("打开 http://127.0.0.1:8502 → 「相似病例」，试试：胸部 / 咳嗽咳痰发热 / 吸烟20年")
    return 0


if __name__ == "__main__":
    sys.exit(main())
