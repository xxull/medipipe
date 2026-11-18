# -*- coding: utf-8 -*-
"""
把 MIMIC / eICU 统一成"病例库"（case_corpus）—— 批量版
=========================================================================
为什么是批量？
-------------------------------------------------------------------------
    第一版按"一个病例一次查询"写，3 千个病例跑了十几分钟还没完。
    原因：200M 行的大库里，每条 SQL 都要扫一遍。

    这一版改成 **一条 SQL 聚合一批**（GROUP_CONCAT），
    每个来源只需几次查询，速度提升几十倍。

输出表
-------------------------------------------------------------------------
    case_corpus
        case_id   唯一标识（miv_<hadm_id> / eicu_<stay_id>）
        source    mimic / eicu
        text      拼出来的病例文本（向量化输入）
        diseases  诊断列表 JSON（统计"类似疾病"）
        drugs     用药列表 JSON（统计"治疗药物"）

用法
-------------------------------------------------------------------------
    python tools\建病例库.py [每家最多几个病例]
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "data" / "records.db"


JUNK = {"no", "none", "n/a", "na", "other", "unknown", "unspecified", "respiratory", "其他", "无", ""}


def clean_list(items, limit: int = 8):
    """过滤掉 "No"/"Other" 这类占位诊断，并去重。"""
    out = []
    for x in items:
        s = str(x or "").strip()
        if not s or s.lower() in JUNK or len(s) < 2:
            continue
        if s not in out:
            out.append(s)
    return out[:limit]


#: 基础列 + 检索/筛选要用的扩展列（dept / age / age_band / gender）
BASE_COLS = [
    ("case_id", "TEXT PRIMARY KEY"), ("source", "TEXT"), ("text", "TEXT"),
    ("diseases", "TEXT"), ("drugs", "TEXT"), ("created_at", "TEXT"),
]
EXTRA_COLS = [("dept", "TEXT"), ("age", "INTEGER"), ("age_band", "TEXT"), ("gender", "TEXT")]

INSERT_SQL = (
    "INSERT OR REPLACE INTO case_corpus"
    " (case_id, source, text, diseases, drugs, created_at)"
    " VALUES (?,?,?,?,?,datetime('now'))"
)


def ensure(conn: sqlite3.Connection) -> None:
    """
    建表 / 补列，但**不删别人写的数据**。

    以前这里是 DROP TABLE 重建，跑一次就把「导入样例数据」写进去的样例、
    以及 dept/age/age_band 这些扩展列一起抹掉了。改成：缺列补列，
    只清掉本脚本负责的来源（mimic / eicu）。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS case_corpus (%s)"
        % ", ".join("%s %s" % (c, t) for c, t in BASE_COLS)
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(case_corpus)")}
    for name, typ in EXTRA_COLS:
        if name not in cols:
            conn.execute("ALTER TABLE case_corpus ADD COLUMN %s %s" % (name, typ))
    conn.execute("CREATE INDEX IF NOT EXISTS idx_case_source ON case_corpus(source)")
    conn.execute("DELETE FROM case_corpus WHERE source IN ('mimic', 'eicu')")
    conn.commit()


def build_mimic(conn: sqlite3.Connection, limit: int) -> int:
    """MIMIC：一次 SQL 把每个住院的诊断拼起来。"""
    print("  MIMIC 聚合中…")
    rows = conn.execute(
        """
        SELECT a.hadm_id,
               GROUP_CONCAT(IFNULL(d.long_title, i.icd_code), '||') AS dis
        FROM (SELECT hadm_id FROM miv_admissions WHERE hadm_id IS NOT NULL LIMIT ?) a
        LEFT JOIN miv_diagnoses_icd i ON i.hadm_id = a.hadm_id
        LEFT JOIN miv_d_icd_diagnoses d
               ON d.icd_code = i.icd_code AND d.icd_version = i.icd_version
        GROUP BY a.hadm_id
        """,
        (limit,),
    ).fetchall()
    print("    拿到 %d 个住院的诊断" % len(rows))

    drugs_map = {}
    for hadm, drugs in conn.execute(
        """
        SELECT a.hadm_id, GROUP_CONCAT(p.drug, '||')
        FROM (SELECT hadm_id FROM miv_admissions WHERE hadm_id IS NOT NULL LIMIT ?) a
        JOIN miv_prescriptions p ON p.hadm_id = a.hadm_id
        WHERE p.drug IS NOT NULL
        GROUP BY a.hadm_id
        """,
        (limit,),
    ):
        drugs_map[hadm] = drugs

    n = 0
    for hadm, dis_text in rows:
        if not dis_text:
            continue
        dis = clean_list(dis_text.split("||"), 8)
        drugs = clean_list((drugs_map.get(hadm) or "").split("||"), 10)
        text = "诊断：%s。用药：%s。" % ("；".join(dis), "、".join(drugs) or "无")
        conn.execute(
            INSERT_SQL,
            ("miv_%s" % hadm, "mimic", text[:1500],
             json.dumps(dis, ensure_ascii=False), json.dumps(drugs, ensure_ascii=False)),
        )
        n += 1
    conn.commit()
    return n


def build_eicu(conn: sqlite3.Connection, limit: int) -> int:
    """eICU：分别聚合 入院诊断 / 既往史 / 用药，再拼。"""
    print("  eICU 聚合中…")
    stays = [r[0] for r in conn.execute(
        "SELECT patientunitstayid FROM eicu_patient LIMIT ?", (limit,)
    )]

    def collect(sql: str) -> dict:
        out = {}
        for pid, val in conn.execute(sql):
            if val:
                out[pid] = [x for x in val.split("||") if x]
        return out

    adm = collect(
        "SELECT patientunitstayid, GROUP_CONCAT(IFNULL(admitdxname, admitdxtext), '||')"
        " FROM eicu_admissiondx GROUP BY patientunitstayid"
    )
    hist = collect(
        "SELECT patientunitstayid, GROUP_CONCAT(pasthistoryvalue, '||')"
        " FROM eicu_pasthistory WHERE pasthistoryvalue IS NOT NULL GROUP BY patientunitstayid"
    )
    dx = collect(
        "SELECT patientunitstayid, GROUP_CONCAT(diagnosisstring, '||')"
        " FROM eicu_diagnosis GROUP BY patientunitstayid"
    )
    med = collect(
        "SELECT patientunitstayid, GROUP_CONCAT(drugname, '||')"
        " FROM eicu_medication WHERE drugname IS NOT NULL GROUP BY patientunitstayid"
    )

    n = 0
    for pid in stays:
        dis = clean_list(adm.get(pid, []) + dx.get(pid, []), 8)
        h = hist.get(pid, [])[:10]
        drugs = clean_list(med.get(pid, []), 10)
        if not dis and not h:
            continue
        text = "入院诊断：%s。既往史：%s。用药：%s。" % (
            "；".join(dis) or "无",
            "；".join(h)[:400] or "无",
            "、".join(drugs) or "无",
        )
        conn.execute(
            INSERT_SQL,
            ("eicu_%s" % pid, "eicu", text[:1500],
             json.dumps(dis, ensure_ascii=False), json.dumps(drugs, ensure_ascii=False)),
        )
        n += 1
    conn.commit()
    return n


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    conn = sqlite3.connect(str(DB), timeout=300)
    conn.execute("PRAGMA synchronous=OFF")
    ensure(conn)

    t0 = time.time()
    print("建病例库（每家最多 %d 个）\n" % limit)
    a = build_mimic(conn, limit)
    print("    -> MIMIC %d 个病例（%.0fs）" % (a, time.time() - t0))
    b = build_eicu(conn, limit)
    print("    -> eICU %d 个病例（%.0fs）" % (b, time.time() - t0))

    total = conn.execute("SELECT COUNT(*) FROM case_corpus").fetchone()[0]
    print("\n完成：共 %d 个病例，用时 %.0f 秒" % (total, time.time() - t0))
    for src in ("mimic", "eicu"):
        row = conn.execute(
            "SELECT COUNT(*), AVG(LENGTH(text)) FROM case_corpus WHERE source=?", (src,)
        ).fetchone()
        print("  %-6s %6d 条，平均文本 %d 字" % (src, row[0], int(row[1] or 0)))
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
