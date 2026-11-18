# -*- coding: utf-8 -*-
"""
给病例库补性别（case_corpus.gender）
=========================================================================
    MIMIC : hadm_id → admissions.subject_id → patients.gender（M/F）
    eICU  : patientunitstayid → patient.gender
    其他  : 留空

用法：
    python tools\补性别.py
"""
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"


def norm(v: str) -> str:
    s = (v or "").strip().upper()
    if s.startswith("M"):
        return "男"
    if s.startswith("F"):
        return "女"
    return ""


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_corpus)")}
    if "gender" not in cols:
        conn.execute("ALTER TABLE case_corpus ADD COLUMN gender TEXT")
        print("已加列 gender")

    t0 = time.time()
    rows = conn.execute("""
        SELECT c.case_id, p.gender
        FROM case_corpus c
        JOIN miv_admissions a ON ('miv_' || a.hadm_id) = c.case_id
        JOIN miv_patients p ON p.subject_id = a.subject_id
        WHERE c.source = 'mimic'
    """).fetchall()
    conn.executemany(
        "UPDATE case_corpus SET gender=? WHERE case_id=?",
        [(norm(g), cid) for cid, g in rows],
    )
    conn.commit()
    print("MIMIC 补了 %d 条（%.0fs）" % (len(rows), time.time() - t0))

    rows = conn.execute("""
        SELECT c.case_id, p.gender
        FROM case_corpus c
        JOIN eicu_patient p ON ('eicu_' || p.patientunitstayid) = c.case_id
        WHERE c.source = 'eicu'
    """).fetchall()
    conn.executemany(
        "UPDATE case_corpus SET gender=? WHERE case_id=?",
        [(norm(g), cid) for cid, g in rows],
    )
    conn.commit()
    print("eICU 补了 %d 条（%.0fs）" % (len(rows), time.time() - t0))

    print("\n性别分布：")
    for g, n in conn.execute(
        "SELECT IFNULL(NULLIF(gender,''),'（未知）'), COUNT(*) FROM case_corpus GROUP BY 1 ORDER BY 2 DESC"
    ):
        print("  %-8s %8d" % (g, n))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
