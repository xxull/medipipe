# -*- coding: utf-8 -*-
"""
相似病例检索（b_相似）
=========================================================================
输入三个字段：哪里不舒服 / 既往病史 / 怎么不舒服
输出三块：  类似疾病统计 / 治疗药物统计 / 总结

原理
-------------------------------------------------------------------------
    1. 把三个字段拼成一句查询文本，用 bge-m3 转成向量
    2. 和全库病例向量的余弦相似度算一遍，取 top-K
    3. 在 top-K 里统计疾病和药物出现次数（次数 / K = 概率）
    4. 总结：本地拼句子；配了主模型就让主模型基于统计写一句

为什么不用"关键词匹配"？
-------------------------------------------------------------------------
    "咳痰伴发热" 和 "咳嗽、有痰、发烧" 关键词对不上，向量能对上。
=========================================================================
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VEC = DATA / "case_vectors.npy"
IDS = DATA / "case_ids.json"
MODEL = "bge-m3:latest"
URL = "http://127.0.0.1:11434/api/embeddings"

_cache: Dict[str, Any] = {}

#: 参与缓存的几个文件：(库、向量、id 列表)。任何一个换了，缓存必须作废
_STAMP_FILES = (DATA / "records.db", DATA / "case_vectors.bin", DATA / "case_ids.jsonl")


def _stamp():
    """这几个文件的 (mtime, size)：用来判断库/向量是不是被重建过。"""
    out = []
    for p in _STAMP_FILES:
        try:
            st = p.stat()
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def _refresh_if_changed() -> None:
    """
    库或向量换了就清缓存。

    踩过的坑：进程里缓存了"性别全空"的掩码，之后跑 `补性别.py` 把库补好了，
    界面还是坚持说「库里没有男」—— 因为缓存永远不失效，只能重启服务。
    现在按文件戳判断，补完字段刷新页面就生效。
    """
    stamp = _stamp()
    if _cache.get("stamp") != stamp:
        _cache.clear()
        _cache["stamp"] = stamp

# 模块级导入：原来写在 show() 里，每调一次就 import 一次（几十微秒 × 每次展示）。
# 词表模块缺失时置 None，调用处已做判空。
try:
    from framework_b.b_诊断词表 import translate_hier as _translate_hier
except Exception:                                   # pragma: no cover
    _translate_hier = None

try:
    from framework_b.b_科室 import group_by_department as _group_depts
except Exception:                                   # pragma: no cover
    _group_depts = None


def _embed(text: str) -> np.ndarray:
    import urllib.request

    payload = json.dumps({"model": MODEL, "prompt": text[:1200]}).encode("utf-8")
    req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        vec = json.loads(r.read().decode("utf-8"))["embedding"]
    v = np.asarray(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n else v


def _zh_map() -> Dict[str, str]:
    """诊断名中英对照（data/disease_zh.json），文件变了自动重载。"""
    path = DATA / "disease_zh.json"
    if not path.exists():
        return {}
    try:
        mtime = path.stat().st_mtime
        if _cache.get("zh_mtime") == mtime:
            return _cache.get("zh") or {}
        data = json.loads(path.read_text(encoding="utf-8"))
        _cache["zh"], _cache["zh_mtime"] = data, mtime
        return data
    except Exception:
        return {}


def _load():
    """
    加载向量矩阵和 id 列表（进程内缓存）。

    优先读 .bin + .jsonl（追加写，构建时不会整文件重写）；
    没有就退回旧的 .npy 格式。
    """
    _refresh_if_changed()
    if _cache.get("mat") is not None:
        return _cache["mat"], _cache["ids"]

    mat = None
    ids = None

    bin_path = DATA / "case_vectors.bin"
    jsonl_path = DATA / "case_ids.jsonl"
    if bin_path.exists() and jsonl_path.exists():
        try:
            flat = np.fromfile(str(bin_path), dtype=np.float32)
            n = flat.size // 1024
            mat = flat[: n * 1024].reshape(n, 1024)
            ids = [x.strip() for x in jsonl_path.read_text(encoding="utf-8").splitlines() if x.strip()][:n]
            mat = mat[: len(ids)]
        except Exception:
            mat, ids = None, None

    if mat is None:
        if not VEC.exists() or not IDS.exists():
            return None, None
        mat = np.load(VEC)
        ids = json.loads(IDS.read_text(encoding="utf-8"))

    # 归一化，之后余弦=点积
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1
    mat = (mat / norms).astype(np.float32)

    _cache["mat"], _cache["ids"] = mat, ids
    return mat, ids


def index_status() -> Dict[str, Any]:
    mat, ids = _load()
    return {
        "ready": mat is not None,
        "count": 0 if mat is None else len(ids),
    }


def _compose_query(where: str, history: str, how: str) -> str:
    """
    把三个输入拼成一句病例描述。

    为什么症状要重复一遍？
    -------------------------------------------------------------------
    实测：三个字段平铺时，"高血压10年"会把相似病例全拉到高血压病史上，
    症状被压过去。症状重复一次 + 病史弱化之后，返回的才是呼吸系统诊断。

    这不是拍脑袋的调参，是 embedding 模型对"出现次数"敏感——
    同一个词出现两次，权重更高。
    """
    symptom = "".join(x.strip() for x in (where, how))
    parts = []
    if symptom:
        parts.append("表现：%s。%s。" % (symptom, symptom))
    if history.strip():
        parts.append("既往史：%s。" % history.strip())
    return "".join(parts)


def _attr_index(n: int) -> Dict[str, int]:
    """case_id → 行号（缓存）。年龄、性别掩码都基于它。"""
    key = "idx_of_%d" % n
    idx = _cache.get(key)
    if idx is not None:
        return idx
    ids = _cache.get("ids") or []
    idx = {cid: i for i, cid in enumerate(ids[:n])}
    _cache[key] = idx
    return idx


def _has_col(conn, table: str, col: str) -> bool:
    """表里有没有这个列（老库 / 只跑过一半初始化脚本时可能缺）。"""
    try:
        return any(r[1] == col for r in conn.execute("PRAGMA table_info(%s)" % table))
    except sqlite3.Error:
        return False


def _gender_mask(n: int) -> Dict[str, np.ndarray]:
    """按性别做掩码（index 顺序与 ids 对齐）。"""
    cached = _cache.get("gender_masks")
    if cached is not None and _cache.get("gender_n") == n:
        return cached

    idx_of = _attr_index(n)
    conn = sqlite3.connect(str(ROOT / "data" / "records.db"), timeout=60)
    try:
        _cache["gender_col"] = _has_col(conn, "case_corpus", "gender")
        if _cache["gender_col"]:
            rows = conn.execute(
                "SELECT IFNULL(gender,''), case_id FROM case_corpus WHERE IFNULL(gender,'')<>''"
            ).fetchall()
        else:
            rows = []
    finally:
        conn.close()

    masks: Dict[str, np.ndarray] = {g: np.zeros(n, dtype=bool) for g in ("男", "女")}
    for g, cid in rows:
        i = idx_of.get(cid)
        if i is not None and g in masks:
            masks[g][i] = True

    _cache["gender_masks"] = masks
    _cache["gender_n"] = n
    # 全是空的话别缓存：多半是还没跑 补性别.py，缓存住就一直显示"没有男/女"
    if not any(m.any() for m in masks.values()):
        _cache.pop("gender_masks", None)
    return masks


def _band_mask(n: int) -> Dict[str, np.ndarray]:
    """
    按年龄段做掩码（index 顺序与 ids 对齐）。

    实现要点：先把 id→行号建成字典（一次 O(n)），
    再按年龄段查库拿 id 列表回填。
    如果对每个 band 都遍历全部 ids，370k 条要 2 秒，每次冷启动都卡一下。
    """
    cached = _cache.get("band_masks")
    if cached is not None and _cache.get("band_n") == n:
        return cached

    ids = _cache.get("ids") or []
    idx_of = {cid: i for i, cid in enumerate(ids[:n])}

    conn = sqlite3.connect(str(ROOT / "data" / "records.db"), timeout=60)
    try:
        _cache["band_col"] = _has_col(conn, "case_corpus", "age_band")
        if _cache["band_col"]:
            rows = conn.execute(
                "SELECT IFNULL(NULLIF(age_band,''),'') AS b, case_id FROM case_corpus"
            ).fetchall()
        else:
            rows = []
    finally:
        conn.close()

    masks: Dict[str, np.ndarray] = {
        band: np.zeros(n, dtype=bool) for band in ("0-17", "18-44", "45-64", "65+")
    }
    for band, cid in rows:
        i = idx_of.get(cid)
        if i is not None and band in masks:
            masks[band][i] = True

    _cache["band_masks"] = masks
    _cache["band_n"] = n
    # 同样：全空不缓存，等用户跑完 补年龄段.py 再算
    if not any(m.any() for m in masks.values()):
        _cache.pop("band_masks", None)
    return masks


def find_similar(
    where: str = "",
    history: str = "",
    how: str = "",
    top_k: int = 30,
    master=None,
    age_band: str = "",
    gender: str = "",
) -> Dict[str, Any]:
    """
    找相似病例并统计。

    返回：
        {"query": 拼出来的查询文本,
         "top_k": 实际使用的 K,
         "diseases": [(疾病, 次数, 概率), ...],
         "drugs":    [(药, 次数, 概率), ...],
         "summary": 一句话总结,
         "usable":  True/False（索引没建好时为 False）}
    """
    text = _compose_query(where, history, how)
    if not text.strip("。 "):
        return {"query": "", "usable": False, "error": "三个输入都是空的", "diseases": [],
                "drugs": [], "summary": ""}

    mat, ids = _load()
    if mat is None:
        return {"query": text, "usable": False, "diseases": [], "drugs": [],
                "error": "向量索引还没建：先跑 tools\\建向量.py",
                "summary": ""}

    q = _embed(text)
    sims = mat @ q

    # 年龄段 / 性别过滤（混合检索的附加维度）
    if age_band:
        mask = _band_mask(len(ids)).get(age_band)
        # 库里没有这个年龄段时，静默忽略会让用户以为筛过了，必须明确报错
        if mask is None or not mask.any():
            if _cache.get("band_col") is False:
                hint = "（病例库没有年龄字段，先跑 python tools\\补年龄段.py）"
            else:
                hint = "，换一个年龄段或选「全部」"
            return {"query": text, "usable": False, "diseases": [], "drugs": [],
                    "departments": [], "summary": "", "matched": [],
                    "error": "库里没有「%s」这个年龄段的病例%s" % (age_band, hint)}
        sims = np.where(mask, sims, -1.0)

    if gender:
        mask = _gender_mask(len(ids)).get(gender)
        if mask is None or not mask.any():
            if _cache.get("gender_col") is False:
                hint = "（病例库没有性别字段，先跑 python tools\\补性别.py）"
            else:
                hint = ""
            return {"query": text, "usable": False, "diseases": [], "drugs": [],
                    "departments": [], "summary": "", "matched": [],
                    "error": "库里没有「%s」的病例%s" % (gender, hint)}
        sims = np.where(mask, sims, -1.0)

    # SQLite 的 SQL 变量上限是 999，top_k 必须夹住，否则 IN (...) 会炸
    top_k = max(1, min(int(top_k or 0), 200))
    k = min(top_k, len(ids))
    idx = np.argpartition(-sims, k - 1)[:k]
    idx = idx[np.argsort(-sims[idx])]
    idx = idx[sims[idx] > -1.0]          # 过滤掉被年龄条件排除的
    if len(idx) == 0:
        return {"query": text, "usable": False, "diseases": [], "drugs": [],
                "summary": "", "error": "这个年龄段里没有匹配的病例，换「全部年龄」试试"}

    # 取 top-K 病例的疾病/药物，做统计
    import sqlite3

    conn = sqlite3.connect(str(ROOT / "data" / "records.db"), timeout=60)
    placeholders = ",".join("?" * len(idx))
    rows = conn.execute(
        "SELECT case_id, source, diseases, drugs FROM case_corpus WHERE case_id IN (%s)" % placeholders,
        [ids[i] for i in idx],
    ).fetchall()
    conn.close()

    # ------------------------------------------------------------------
    # 来源相等加权
    # ------------------------------------------------------------------
    # 不同来源的信息量差很多：MIMIC 每例带 8 个诊断，中文问答只有 1-2 个。
    # 直接混着数，MIMIC 会把中文数据淹掉。所以：
    #     先算每个来源内部的百分比，再把各来源的百分比取平均。
    # 这样三个来源对最终统计的贡献一样大（用户选的"相等"）。
    per_src_n: Counter = Counter()
    per_src_dis: Dict[str, Counter] = {}
    per_src_drug: Dict[str, Counter] = {}
    for _cid, src, dis_json, drug_json in rows:
        per_src_n[src] += 1
        per_src_dis.setdefault(src, Counter())
        per_src_drug.setdefault(src, Counter())
        try:
            for d in json.loads(dis_json or "[]"):
                if d:
                    per_src_dis[src][d] += 1
        except Exception:
            pass
        try:
            for g in json.loads(drug_json or "[]"):
                if g:
                    per_src_drug[src][g] += 1
        except Exception:
            pass

    def merge(counters: Dict[str, Counter], total_n: Counter) -> Counter:
        """把各来源的计数换成"来源内比例"，再按比例平均。"""
        srcs = [s for s in counters if total_n.get(s)]
        if not srcs:
            return Counter()
        acc: Counter = Counter()
        for s in srcs:
            n = total_n[s]
            for name, c in counters[s].items():
                acc[name] += c / n
        for name in list(acc):
            acc[name] /= len(srcs)
        return acc

    kk = max(1, len(rows))
    # 合并后是"平均比例"，换算成次数展示时统一乘 kk
    dis_ratio = merge(per_src_dis, per_src_n)
    drug_ratio = merge(per_src_drug, per_src_n)
    dis_counter = Counter({k: round(v * kk) for k, v in dis_ratio.items()})
    drug_counter = Counter({k: round(v * kk) for k, v in drug_ratio.items()})

    zh = _zh_map()

    def show(name: str) -> str:
        """有中文就用中文；层级名逐段翻译；长尾没翻到的保留英文。"""
        if name in zh:
            return zh[name]
        if "|" in name:
            # 模块级导入（原来写在这里，每调一次 show 就 import 一次）
            return _translate_hier(name) if _translate_hier else name
        return name

    # 注意：这里要带占比（3 元组），科室分组要用
    diseases_en = [(d, n, round(n / kk, 3)) for d, n in dis_counter.most_common(10)]
    diseases = [(show(d), n, p) for d, n, p in diseases_en]
    drugs = [(show(g), n, round(n / kk, 3)) for g, n in drug_counter.most_common(10)]

    # 按科室汇总，检索结果更有指向性
    try:
        departments = _group_depts(diseases_en) if _group_depts else []
    except Exception:
        departments = []

    summary = _summarize(text, kk, diseases, drugs, master)
    return {
        "query": text,
        "usable": True,
        "top_k": kk,
        "matched": [ids[i] for i in idx[:10]],
        "diseases": diseases,
        "diseases_en": diseases_en,
        "departments": departments,
        "drugs": drugs,
        "summary": summary,
    }


def _summarize(text: str, kk: int, diseases, drugs, master=None) -> str:
    """总结：优先让主模型写一句；没有主模型就用模板。"""
    if not diseases:
        return "没有找到足够相似的病例，换个说法再试。"

    top_d = "、".join("%s（%d/%d）" % (d, n, kk) for d, n, _p in diseases[:3])
    top_g = "、".join("%s（%d 次）" % (g, n) for g, n, _p in drugs[:3]) or "无"

    if master is None:
        return ("在 %d 个相似病例里，最常见的诊断是 %s；用到的治疗药物主要是 %s。"
                "（本地统计，未调用模型）" % (kk, top_d, top_g))

    try:
        prompt = (
            "下面是 %d 个相似病例的统计结果（不是单个病人）。\n"
            "最常见诊断：%s\n最常见用药：%s\n"
            "请用两句话总结这批相似病例的共性，不要说诊断结论，不要给治疗建议。"
            % (kk, top_d, top_g)
        )
        out = master.chat(
            "你是医疗数据分析助手。只描述统计现象，不做诊断、不给治疗建议。",
            prompt, max_tokens=200,
        )
        return (out or "").strip() or "（主模型没有返回内容）"
    except Exception as exc:
        return "（主模型不可用：%s）%s" % (exc, "统计结果见上表。")


def detail(case_id: str) -> Dict[str, Any]:
    """取单个病例详情（内部走批次接口）。"""
    return details([case_id]).get(case_id, {"error": "找不到这个病例：%s" % case_id})


def details(case_ids) -> Dict[str, Dict[str, Any]]:
    """
    批量取病例详情：**只开一次数据库连接**。

    之前是每个病例开一次连接，界面上展示 10 条候选就是 10 次连接，
    在 40 GB 的库上纯属浪费（每次连接还要重跑 PRAGMA）。
    """
    import sqlite3

    conn = sqlite3.connect(str(ROOT / "data" / "records.db"), timeout=60)
    try:
        return {cid: _detail_with(conn, cid) for cid in case_ids}
    finally:
        conn.close()


def _one(conn, sql: str, args=()):
    """
    查一行；表不存在就返回 None。

    公开版仓库里没有 MIMIC/eICU/Huatuo/dayi 那些表，详情页不能因为
    "某张可选表不存在"就整条报错。
    """
    import sqlite3

    try:
        return conn.execute(sql, args).fetchone()
    except sqlite3.Error:
        return None


def _detail_with(conn, case_id: str) -> Dict[str, Any]:
    """
    在一个已有连接上取详情（不负责开关连接）。

    三种来源结构完全不同，这里统一成同样的字段：
        {"case_id", "source", "text", "diseases", "drugs", "extra"}
    """
    if True:
        row = conn.execute(
            "SELECT source, text, diseases, drugs FROM case_corpus WHERE case_id=?", (case_id,)
        ).fetchone()
        if not row:
            return {"error": "找不到这个病例：%s" % case_id}
        source, text, dis_json, drug_json = row
        out: Dict[str, Any] = {
            "case_id": case_id,
            "source": source,
            "text": text,
            "diseases": json.loads(dis_json or "[]"),
            "drugs": json.loads(drug_json or "[]"),
            "extra": {},
        }

        if case_id.startswith("miv_"):
            hadm = case_id[4:]
            adm = _one(
                conn,
                "SELECT admittime, dischtime, admission_type, hospital_expire_flag"
                " FROM miv_admissions WHERE hadm_id=?", (hadm,)
            )
            if adm:
                out["extra"]["住院信息"] = {
                    "入院": adm[0], "出院": adm[1], "类型": adm[2],
                    "院内死亡": "是" if str(adm[3]) == "1" else "否",
                }
            note = _one(
                conn, "SELECT text FROM note_discharge WHERE hadm_id=? LIMIT 1", (hadm,)
            )
            if note:
                out["extra"]["出院小结（节选）"] = str(note[0])[:1500]

        elif case_id.startswith("eicu_"):
            pid = case_id[5:]
            try:
                his = [r[0] for r in conn.execute(
                    "SELECT pasthistoryvalue FROM eicu_pasthistory WHERE patientunitstayid=? LIMIT 15",
                    (pid,)) if r[0]]
            except sqlite3.Error:
                his = []
            if his:
                out["extra"]["既往史"] = "；".join(dict.fromkeys(his))[:800]

        elif case_id.startswith("ht_"):
            qid = case_id[3:]
            qa = _one(
                conn, "SELECT question, answer, label FROM huatuo_qa WHERE id=?", (qid,)
            )
            if qa:
                out["extra"]["科室"] = qa[2]
                out["extra"]["问答原文"] = "问：%s\n答：%s" % (str(qa[0])[:800], str(qa[1])[:800])

        return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python framework_b\\b_相似.py <不适部位> <既往史> <怎么不舒服>")
        sys.exit(0)
    where, hist, how = (sys.argv + ["", "", ""])[1:4]
    r = find_similar(where, hist, how, top_k=20)
    print(json.dumps(r, ensure_ascii=False, indent=2)[:2000])
