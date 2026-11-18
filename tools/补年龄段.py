# -*- coding: utf-8 -*-
"""
给病例库补年龄段（case_corpus.age）
=========================================================================
混合检索要用年龄收窄范围，所以先把年龄落到病例上：

    MIMIC : hadm_id → admissions.subject_id → patients.anchor_age
    eICU  : patientunitstayid → patient.age（字符串，可能 >89 或空）
    其他  : 留空

用法：
    python tools\补年龄段.py
"""
import re
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"

#: 年龄段划分（和临床常用分组一致）
BANDS = [(0, 17, "0-17"), (18, 44, "18-44"), (45, 64, "45-64"), (65, 200, "65+")]


def band(age) -> str:
    try:
        a = int(age)
    except (TypeError, ValueError):
        return ""
    for lo, hi, name in BANDS:
        if lo <= a <= hi:
            return name
    return ""


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_corpus)")}
    if "age" not in cols:
        conn.execute("ALTER TABLE case_corpus ADD COLUMN age INTEGER")
        print("已加列 age")
    if "age_band" not in cols:
        conn.execute("ALTER TABLE case_corpus ADD COLUMN age_band TEXT")
        print("已加列 age_band")

    t0 = time.time()

    # ---- MIMIC ----
    rows = conn.execute("""
        SELECT c.case_id, p.anchor_age
        FROM case_corpus c
        JOIN miv_admissions a ON ('miv_' || a.hadm_id) = c.case_id
        JOIN miv_patients p ON p.subject_id = a.subject_id
        WHERE c.source = 'mimic'
    """).fetchall()
    upd = [(int(r[1]) if str(r[1]).isdigit() else None, band(r[1]), r[0]) for r in rows]
    conn.executemany("UPDATE case_corpus SET age=?, age_band=? WHERE case_id=?", upd)
    conn.commit()
    print("MIMIC 补了 %d 条（%.0fs）" % (len(upd), time.time() - t0))

    # ---- eICU ----
    rows = conn.execute("""
        SELECT c.case_id, p.age
        FROM case_corpus c
        JOIN eicu_patient p ON ('eicu_' || p.patientunitstayid) = c.case_id
        WHERE c.source = 'eicu'
    """).fetchall()
    upd = []
    for cid, age in rows:
        m = re.search(r"\d+", str(age or ""))
        a = int(m.group(0)) if m else None
        upd.append((a, band(a), cid))
    conn.executemany("UPDATE case_corpus SET age=?, age_band=? WHERE case_id=?", upd)
    conn.commit()
    print("eICU 补了 %d 条（%.0fs）" % (len(upd), time.time() - t0))

    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_band ON case_corpus(age_band)")
    conn.commit()

    print("\n年龄段分布：")
    for b, n in conn.execute(
        "SELECT IFNULL(NULLIF(age_band,''),'（未知）'), COUNT(*) FROM case_corpus"
        " GROUP BY 1 ORDER BY 2 DESC"
    ):
        print("  %-8s %8d" % (b, n))
    conn.close()
    print("\n用时 %.0f 秒" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
