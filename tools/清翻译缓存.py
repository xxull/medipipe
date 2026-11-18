# -*- coding: utf-8 -*-
"""
清理翻译缓存里的坏译文
=========================================================================
什么算坏
-------------------------------------------------------------------------
* 目标是英文，译文里还有汉字  → 模型原样返回了输入
* 目标是中文，译文里一个汉字都没有 → 同上，反过来
* 空字符串

这类条目会被后续请求当成"已翻好"，于是界面一直显示原文。
b_翻译 现在会拦，但历史缓存要手动清一次。

用法
-------------------------------------------------------------------------
    python tools\\清翻译缓存.py          # 只看，不删
    python tools\\清翻译缓存.py --apply  # 真删
=========================================================================
"""
import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "records.db"

CJK = re.compile(r"[\u4e00-\u9fff]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的删除（默认只看）")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print("找不到数据库：%s" % db)
        return 1

    conn = sqlite3.connect(str(db), timeout=60)
    try:
        rows = conn.execute("SELECT h, target, text FROM translate_cache").fetchall()
    except sqlite3.Error as exc:
        print("读不到 translate_cache：%s" % exc)
        conn.close()
        return 1

    bad = []
    for h, target, text in rows:
        t = (text or "").strip()
        if not t:
            bad.append((h, target, t))
        elif target == "en" and CJK.search(t):
            bad.append((h, target, t))
        elif target == "zh" and not CJK.search(t):
            bad.append((h, target, t))

    print("缓存共 %d 条，坏译文 %d 条" % (len(rows), len(bad)))
    for h, target, t in bad[:10]:
        print("  [%s] %s" % (target, t[:50]))

    if bad and args.apply:
        conn.executemany("DELETE FROM translate_cache WHERE h=?", [(h,) for h, _, _ in bad])
        conn.commit()
        print("已删除 %d 条" % len(bad))
    elif bad:
        print("（只看不删，加 --apply 真删）")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
