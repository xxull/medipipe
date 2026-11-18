# -*- coding: utf-8 -*-
"""
命令行演示：不开界面，直接看检索效果
=========================================================================
用来快速确认「库里有东西、检索能出结果」，也方便录屏/截图。

用法
-------------------------------------------------------------------------
    python tools\\演示_检索.py
    python tools\\演示_检索.py 咳嗽
=========================================================================
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from framework_b import b_检索, b_相似  # noqa: E402


def line(title=""):
    if title:
        print("\n" + title)
        print("-" * min(72, 8 + len(title) * 2))


def main() -> int:
    kw = sys.argv[1] if len(sys.argv) > 1 else "咳嗽"

    line("① 关键词检索（FTS5 + 中文二元分词）")
    t0 = time.time()
    hits = b_检索.search_fts(kw, limit=5)
    used = "全文索引"
    if not hits:
        hits = b_检索.search(kw, limit=5)
        used = "LIKE 兜底"
    print("查询：%s   方式：%s   命中 %d 条   用时 %.2f 秒"
          % (kw, used, len(hits), time.time() - t0))
    for i, h in enumerate(hits, 1):
        rec = h.get("record") or {}
        text = (rec.get("文本") or rec.get("疾病") or rec.get("brand_name")
                or rec.get("问") or rec.get("名称") or str(rec))
        print("  %d. [%-11s] %s" % (i, h["table"], str(text)[:60]))

    line("② 相似病例（向量 + 年龄段/性别）")
    t0 = time.time()
    r = b_相似.find_similar("胸部", "吸烟20年", "咳嗽咳痰、发热三天",
                            top_k=10, master=None, age_band="", gender="")
    if not r.get("usable"):
        print("  " + str(r.get("error")))
    else:
        print("  命中 %d 例，用时 %.2f 秒" % (len(r["matched"]), time.time() - t0))
        print("  常见诊断：" + "、".join("%s(%d)" % (d, n) for d, n, _p in r["diseases"][:3]))
        print("  常用药物：" + "、".join("%s(%d)" % (d, n) for d, n, _p in r["drugs"][:3]))
        if r.get("departments"):
            d = r["departments"][0]
            print("  科室分布：%s（%d 例）" % (d["科室"], d["次数"]))
        print("  一句话总结：" + str(r.get("summary"))[:80])

    line("③ 药品说明")
    from framework_b import b_说明

    for name in ("Metformin Hydrochloride", "阿莫西林"):
        d = b_说明.drug(name)
        print("  %-24s → %s" % (name, (d.get("来源") or "（库里没有）")[:40]))

    print("\n提示：以上结果都来自 data/records.db；没有数据先跑 导入样例数据.py / 导入开放数据.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
