# -*- coding: utf-8 -*-
"""
Framework B · 界面（app_b）
=========================================================================
五个标签页：

    概览        库里有什么
    相似病例    部位选择/自由输入/上传病历 → 疾病、科室、药物、总结、原始病例
    关键词检索  全文索引（BM25）+ 结果翻译
    病历总结    文字或图片 → 六段式提炼
    自检        三个灯 + 主模型 Key（可选）

启动：
    python -m streamlit run framework_b/app_b.py --server.port=8502
=========================================================================
"""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "framework_b")):
    if p not in sys.path:
        sys.path.insert(0, p)

from framework_b import b_核心, b_检索, b_相似, b_总结, b_药物  # noqa: E402

DB = ROOT / "data" / "records.db"
st.set_page_config(page_title="Framework B · 检索应用", page_icon="🔎", layout="wide")

#: 人体部位（点选，也可以自己填）
BODY_PARTS = ["头面部", "颈部", "胸部", "腹部", "腰背部", "上肢", "下肢",
              "皮肤", "泌尿生殖", "全身"]


def _light(name: str, ok: bool, detail: str) -> None:
    color = "#3fb950" if ok else "#f85149"
    st.markdown(
        '<div style="display:inline-block;margin:2px 8px 2px 0;padding:6px 10px;'
        'border:1px solid %s;border-radius:6px;color:#e6edf3;font-size:13px;">'
        '<span style="color:%s">●</span> %s：%s</div>' % (color, color, name, detail),
        unsafe_allow_html=True,
    )


@st.cache_data(ttl=300, show_spinner=False)
def _counts() -> dict:
    """
    各数据源行数。

    用 SQLite 的 sqlite_stat1（ANALYZE 的结果）而不是 MAX(rowid)：
    后者在"主键就是 rowid"的表上等于最大 id，会算出天文数字（实测 2.9 万亿）。
    没有统计的表退回 COUNT(*)，并标注为估算。
    """
    conn = sqlite3.connect(str(DB), timeout=60)

    stat1 = {}
    try:
        for tbl, stat in conn.execute("SELECT tbl, stat FROM sqlite_stat1"):
            try:
                stat1[tbl] = int(str(stat).split()[0])
            except Exception:
                pass
    except Exception:
        pass

    def rows_of(table: str) -> int:
        if table in stat1:
            return stat1[table]
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM (SELECT 1 FROM \"%s\" LIMIT 500001)"
                % table.replace('"', '""')).fetchone()[0]
        except Exception:
            return 0

    out = {}
    for prefix, label in (("miv_", "MIMIC-IV"), ("eicu_", "eICU"), ("ed_", "MIMIC-ED"),
                          ("note_", "MIMIC-Note"), ("huatuo_", "Huatuo-QA"), ("dayi_", "中文说明书")):
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?", (prefix + "%",))]
        tables = [t for t in tables if not t.lower().endswith(("_data", "_idx", "_content",
                                                              "_docsize", "_config"))]
        out[label] = (len(tables), sum(rows_of(t) for t in tables))
    out["药品"] = (0, rows_of("drugs"))
    out["病例库"] = (0, rows_of("case_corpus"))
    conn.close()
    return out


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------
def _page_overview() -> None:
    c = _counts()
    idx = b_相似.index_status()

    st.markdown("### 数据概览")
    cols = st.columns(4)
    for col, (label, value, hint) in zip(cols, [
        ("病例库", c.get("病例库", (0, 0))[1], "可用于相似检索"),
        ("向量索引", idx["count"], "已建向量" if idx["ready"] else "未建"),
        ("药品", c.get("药品", (0, 0))[1], "openFDA"),
        ("MIMIC-IV", c.get("MIMIC-IV", (0, 0))[1], "行"),
    ]):
        col.metric(label, format(value, ","), hint)

    st.markdown("### 各数据源")
    st.dataframe(
        [{"数据源": k, "表数": c.get(k, (0, 0))[0], "行数": format(c.get(k, (0, 0))[1], ",")}
         for k in ("MIMIC-IV", "eICU", "MIMIC-ED", "MIMIC-Note", "Huatuo-QA")],
        width="stretch", hide_index=True,
    )

    try:
        conn = sqlite3.connect(str(DB), timeout=60)
        src = conn.execute("SELECT source, COUNT(*) FROM case_corpus GROUP BY source").fetchall()
        band = conn.execute(
            "SELECT IFNULL(NULLIF(age_band,''),'未知'), COUNT(*) FROM case_corpus"
            " GROUP BY 1 ORDER BY 2 DESC").fetchall()
        conn.close()
        c1, c2 = st.columns(2)
        with c1:
            st.caption("按来源")
            st.dataframe([{"来源": s, "条数": format(n, ",")} for s, n in src],
                         width="stretch", hide_index=True)
        with c2:
            st.caption("按年龄段")
            st.dataframe([{"年龄段": a, "条数": format(n, ",")} for a, n in band],
                         width="stretch", hide_index=True)
    except Exception as exc:
        st.info("统计失败：%s" % exc)


# ---------------------------------------------------------------------------
# 相似病例
# ---------------------------------------------------------------------------
def _drug_table(dis_en, dis_zh, case_drugs, target: str = "原文") -> None:
    """
    ③ 常用药物：中文说明书 → 相似病例实际用药 → openFDA 兜底。

    注意：dis_en / dis_zh 传进来是**名字列表**（调用方已经拆过元组），
    不要再二次解包，否则字符串会被当成元组拆。
    """
    from framework_b import b_翻译

    # 选了中文就把疾病名先转成中文，否则拿英文名去中文说明书里查必然查不到
    zh_names = list(dis_zh or [])
    if target == "zh" and dis_en:
        names = [str(x) for x in dis_en][:6]
        zh_names = list(dict.fromkeys(zh_names + list(b_翻译.batch(names, "zh").values())))

    st.markdown("**中文说明书（按适应症匹配，来源：中国医药信息查询平台）**")
    zh_rows = []
    for name in zh_names[:4]:
        zh_rows += b_药物.for_disease_zh(name, limit=4)
    seen, uniq = set(), []
    for r in zh_rows:
        if r["药物"] in seen:
            continue
        seen.add(r["药物"])
        uniq.append(r)
    if uniq:
        _clickable_table(uniq[:8], key="tbl_zh_drug", kind="drug", name_col="药物")
        st.caption("匹配依据是说明书里的「适应症」原文。只作参考，**不是处方建议**。")
    elif b_药物.has_zh_labels():
        st.info("中文说明书里没有匹配到该适应症的药物。")
    else:
        st.caption("本库没有中文药品说明书（公开版只带 openFDA 英文数据），下面看「英文药品库兜底」。")

    st.markdown("**相似病例里实际用过的药**")
    if case_drugs:
        rows = [{"药物": g, "次数": n, "占比": "%.0f%%" % (p * 100)} for g, n, p in case_drugs]
        if target != "原文":
            # 药名是英文的，按语言设置批量翻一次（结果进缓存，之后秒出）
            mapping = b_翻译.batch([r["药物"] for r in rows], target)
            rows = [{**r, "药物": mapping.get(r["药物"], r["药物"])} for r in rows]
        _clickable_table(rows, key="tbl_case_drug", kind="drug", name_col="药物")
    else:
        st.info("这批病例没有用药记录（中文问答本身不含用药字段）")

    st.markdown("**英文药品库兜底（openFDA）**")
    rows = b_药物.for_diseases(dis_en, limit=4)
    bad = ("sunscreen", "sunburn", "skin", "makeup", "lotion", "spray", "moistur")
    rows = [r for r in rows if r["质量分"] >= 50
            and not any(b in (r["药物"] or "").lower() for b in bad)]
    if rows:
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.caption("没有匹配（openFDA 以美国 OTC 标签为主，覆盖有限）")


def _clickable_table(rows, key: str, kind: str, name_col: str) -> None:
    """
    可点选的表格：点某一行就展开它的说明。

    kind = "disease" 查疾病说明，kind = "drug" 查药物说明书。
    """
    if not rows:
        return
    event = st.dataframe(
        rows, width="stretch", hide_index=True,
        on_select="rerun", selection_mode="single-row", key=key,
    )
    picked = getattr(event, "selection", {}) or {}
    idx = picked.get("rows") or []
    if not idx:
        st.caption("💡 点表格里任意一行，可以看这个%s的说明。" % ("病" if kind == "disease" else "药"))
        return

    from framework_b import b_说明

    name = rows[idx[0]].get(name_col, "")
    info = b_说明.disease(name) if kind == "disease" else b_说明.drug(name)
    if not info:
        st.warning("没有找到「%s」的说明" % name)
        return

    lines = ["**%s**（来源：%s）" % (info.get("名称", name), info.get("来源", ""))]
    if info.get("类型"):
        lines.append("类型：%s" % info["类型"])
    for k, v in (info.get("要点") or {}).items():
        lines.append("**%s**：%s" % (k, str(v)[:400]))
    st.info("\n\n".join(lines))
    if info.get("链接"):
        st.caption("原始页面：%s" % info["链接"])


def _page_similar() -> None:
    status = b_相似.index_status()
    if not status["ready"]:
        st.warning("向量索引还没建：先跑 python tools\\建向量.py")
        return

    st.caption("已建向量 %s 条。可以直接选部位，也可以粘/拍一份病历让它自己找。"
               % format(status["count"], ","))

    # ---- 输入 ----
    parts = st.multiselect(
        "① 哪里不舒服（可多选，也可以自己在下面填）",
        BODY_PARTS, default=[],
        help="选中的部位会拼进查询；不在列表里的部位直接写在下面的输入框。",
    )
    c1, c2 = st.columns(2)
    with c1:
        where_free = st.text_input("部位（自由填写，可留空）", placeholder="例如：右下腹、甲状腺")
    with c2:
        how = st.text_input("② 怎么不舒服", placeholder="咳嗽有痰、发热三天")
    hist = st.text_input("③ 既往病史", placeholder="高血压10年、吸烟30年")

    with st.expander("④ 直接给一份病历（粘贴或上传照片，自动提取后找相似）"):
        note = st.text_area("病历文本", height=120, placeholder="主诉：… 现病史：…")
        img = st.file_uploader("或上传病历照片", type=["png", "jpg", "jpeg", "webp"])
        if img is not None and st.button("识别图片"):
            tmp = ROOT / "data" / ("_upload_%s" % img.name)
            tmp.write_bytes(img.getbuffer())
            with st.spinner("读图中…"):
                try:
                    st.session_state["note_text"] = b_总结.read_image(str(tmp))
                    st.success("识别完成，已填入下方")
                except Exception as exc:
                    st.error("读图失败：%s" % exc)
        if st.session_state.get("note_text"):
            note = st.text_area("识别/粘贴结果", value=st.session_state["note_text"],
                                height=120, key="note_edit")

    c7, c8 = st.columns(2)
    with c7:
        band = st.selectbox("年龄段（可选）", ["全部", "0-17", "18-44", "45-64", "65+"], index=0)
    with c8:
        gender = st.selectbox(
            "性别（可选）", ["全部", "男", "女"], index=0,
            help="选性别可以排除不相关的病种，比如男性不会返回妇产科病例。",
        )

    c5, c6 = st.columns([1, 3])
    with c5:
        go = st.button("找相似病例", type="primary", width="stretch",
                       disabled=not (parts or where_free or how or hist or note))
    with c6:
        st.caption("症状权重高于病史；给了病历就优先用病历里的描述。")

    # 同关键词检索：按钮只在点击那次为 True。
    # 语言单选/tab 切换会重跑脚本，直接 return 会让结果"弹回去"，
    # 所以结果存 session_state，之后都用存下来的渲染。
    if go:
        where = "、".join([p for p in parts] + ([where_free] if where_free.strip() else []))
        # 有整段病历时，把它当成"怎么不舒服"的一部分（信息量最大）
        how_full = how if not note.strip() else (how + "。" + note.strip()[:800]).strip("。")
        # 新的一次检索：把上次的翻译结果清掉，避免显示成上一批的内容
        st.session_state["sim_tr_target"] = None
        st.session_state["sim_tr_rows"] = None
        with st.spinner("检索中…"):
            st.session_state["sim_result"] = b_相似.find_similar(
                where, hist, how_full, top_k=30,
                age_band="" if band == "全部" else band,
                gender="" if gender == "全部" else gender,
            )

    r = st.session_state.get("sim_result")
    if not r:
        return

    if not r.get("usable"):
        st.error(r.get("error") or "检索失败")
        return

    m1, m2 = st.columns([1, 3])
    m1.metric("相似病例", r["top_k"])
    m2.caption("查询：" + r["query"][:160])

    # ---- 语言切换（显式按钮，不再藏在下拉里）----
    lang = st.radio("结果语言", ["原文", "中文", "English"], horizontal=True, index=0,
                    help="翻译只影响显示；点「恢复原文」可以随时切回去。")

    def show_table(rows, target, tag):
        if target == "原文":
            st.dataframe([{tag: d, "次数": n, "占比": "%.0f%%" % (p * 100)} for d, n, p in rows],
                         width="stretch", hide_index=True)
            return
        cache_key = "tr_%s_%s" % (tag, target)
        if st.button("翻译（%s）" % ("中文" if target == "zh" else "English"), key="btn_" + cache_key):
            with st.spinner("翻译中…"):
                from framework_b import b_翻译

                st.session_state[cache_key] = [(b_翻译.text(d, target), n, p) for d, n, p in rows]
        if st.session_state.get(cache_key):
            st.dataframe(
                [{tag: d, "次数": n, "占比": "%.0f%%" % (p * 100)}
                 for d, n, p in st.session_state[cache_key]],
                width="stretch", hide_index=True)
            if st.button("恢复原文", key="rst_" + cache_key):
                st.session_state[cache_key] = None
                st.rerun()
        else:
            st.dataframe([{tag: d, "次数": n, "占比": "%.0f%%" % (p * 100)} for d, n, p in rows],
                         width="stretch", hide_index=True)

    target = {"原文": "原文", "中文": "zh", "English": "en"}[lang]

    # 翻译做成"按钮触发"，不自动跑：
    # 自动翻要等十几秒，用户可能只是想看看英文原文。
    # 第一次点约 20 秒，之后同内容走磁盘缓存，秒出。
    from framework_b import b_翻译

    dis_rows = r["diseases"]
    drug_rows = r["drugs"]
    depts = r.get("departments") or []
    zh_lang_name = "中文" if target == "zh" else "English"

    if target != "原文":
        ctr1, ctr2 = st.columns([1.4, 3])
        with ctr1:
            do_tr = st.button("翻译成%s" % zh_lang_name, key="btn_sim_tr", width="stretch",
                              help="把疾病名和药名翻译成目标语言。首次约 20 秒（本地模型），"
                                   "同一批内容再点会秒出。")

        # 注意顺序：必须**先算再显示状态**。
        # 以前把状态显示写在计算前面，点完按钮这一轮页面已经画完旧状态，
        # 于是「已翻译 / 恢复原文」要等用户再点一次别的东西才冒出来。
        if do_tr:
            if not b_翻译.preflight():
                st.error("本地模型没启动（Ollama 不是运行状态）。"
                         "请先启动 Ollama，或到「自检」页看本地模型那盏灯。")
            else:
                t_tr = time.time()
                with st.spinner("正在翻译（本机模型要逐条推理，约 20–40 秒，请稍等）…"):
                    names = [d for d, _n, _p in dis_rows]
                    mapping = b_翻译.batch(names, target)
                    new_dis = [(mapping.get(d, d), n, p) for d, n, p in dis_rows]
                    new_drug = drug_rows
                    if drug_rows:
                        dm = b_翻译.batch([g for g, _n, _p in drug_rows], target)
                        new_drug = [(dm.get(g, g), n, p) for g, n, p in drug_rows]
                    # 科室分布里的「代表疾病」也是英文诊断名，得一起翻，
                    # 否则会出现「科室=呼吸内科、代表疾病=Cellulitis…」这种中英混排
                    new_depts = depts
                    if depts:
                        dept_names = [x["name"] for d in depts for x in d.get("疾病", [])]
                        dm2 = b_翻译.batch(dept_names, target) if dept_names else {}
                        new_depts = [
                            {
                                **d,
                                "疾病": [{**x, "name": dm2.get(x["name"], x["name"])}
                                         for x in d.get("疾病", [])],
                            }
                            for d in depts
                        ]
                st.session_state["sim_tr_rows"] = {
                    "dis": new_dis, "drug": new_drug, "dept": new_depts}
                st.session_state["sim_tr_target"] = target
                st.session_state["sim_tr_ms"] = int((time.time() - t_tr) * 1000)

        with ctr2:
            if st.session_state.get("sim_tr_target") == target:
                ms = st.session_state.get("sim_tr_ms") or 0
                st.caption("✅ 已翻译（%s，用时 %.1f 秒）。点「恢复原文」可以切回。"
                           % (zh_lang_name, ms / 1000.0))
                if st.button("恢复原文", key="btn_sim_rst"):
                    st.session_state["sim_tr_target"] = None
                    st.session_state["sim_tr_rows"] = None
                    st.rerun()
            else:
                st.caption("点按钮后约需 20 秒。不点就显示原文。")

        if st.session_state.get("sim_tr_target") == target and st.session_state.get("sim_tr_rows"):
            dis_rows = st.session_state["sim_tr_rows"]["dis"]
            drug_rows = st.session_state["sim_tr_rows"]["drug"]
            depts = st.session_state["sim_tr_rows"].get("dept") or depts

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["① 类似疾病", "② 治疗药物", "③ 常用药物", "④ 总结", "⑤ 查看病例"])

    with tab1:
        # 疾病表可点选：点一行就能看这个病的说明
        _clickable_table(
            [{"疾病": d, "次数": n, "占比": "%.0f%%" % (p * 100)} for d, n, p in dis_rows],
            key="tbl_dis", kind="disease", name_col="疾病")
        if depts:
            st.markdown("**科室分布（参考）**")
            st.dataframe(
                [{"科室": d["科室"], "次数": d["次数"],
                  "代表疾病": "、".join(x["name"] for x in d["疾病"][:3])} for d in depts],
                width="stretch", hide_index=True)

    with tab2:
        if drug_rows:
            _clickable_table(
                [{"药物": g, "次数": n, "占比": "%.0f%%" % (p * 100)} for g, n, p in drug_rows],
                key="tbl_drug", kind="drug", name_col="药物")
        else:
            st.info("这批相似病例没有用药记录")

    with tab3:
        _drug_table(
            [d for d, _n, _p in r.get("diseases_en") or []],
            [d for d, _n, _p in r.get("diseases") or []],
            r["drugs"],
            target=target,
        )

    with tab4:
        st.write(r["summary"])

    with tab5:
        st.caption("点开看原始记录（MIMIC 带出院小结节选，eICU 带既往史，中文问答带原文）")
        # 一次开连接取全部候选，而不是在循环里逐个查库
        top_ids = (r.get("matched") or [])[:10]
        detail_map = b_相似.details(top_ids) if top_ids else {}
        for cid in top_ids:
            d = detail_map.get(cid) or {}
            if d.get("error"):
                st.warning(d["error"])
                continue
            with st.expander("%s · %s" % (cid, d.get("source"))):
                if d.get("diseases"):
                    st.markdown("**诊断**：" + "、".join(d["diseases"][:8]))
                if d.get("drugs"):
                    st.markdown("**用药**：" + "、".join(d["drugs"][:10]))
                for k, v in (d.get("extra") or {}).items():
                    st.markdown("**%s**" % k)
                    st.text(str(v)[:1200])
                st.caption("语料：" + str(d.get("text"))[:300])


# ---------------------------------------------------------------------------
# 关键词检索
# ---------------------------------------------------------------------------
def _page_search() -> None:
    st.caption("全文索引（倒排 + BM25），中文按二元分词，一般 0.3 秒内返回。")
    question = st.text_input("想问什么", placeholder="胃癌 / metformin / 阿司匹林 头痛",
                             label_visibility="collapsed",
                             help="中英文都支持；多个词时命中越多的排前面。")

    c1, c2, c3 = st.columns([1, 1.2, 1.2])
    with c1:
        go = st.button("查询", type="primary", width="stretch", disabled=not question.strip())
    with c2:
        gate = st.selectbox("质量门槛", ["全部", "质量分 ≥ 70", "只看有元数据的"],
                            help="只对药品表生效")
    with c3:
        lang = st.radio("结果语言", ["原文", "中文", "English"], horizontal=True,
                        help="翻译只影响显示，可随时恢复")

    # 按钮只在"点下的那一次"为 True。语言/质量门槛这种控件一改，脚本会重跑，
    # 如果这里直接 return，结果就消失了 —— 用户看到的就是"一切换就弹回去"。
    # 所以把结果存进 session_state，之后无论怎么切换控件都用存下来的结果渲染。
    if go:
        t0 = time.time()
        hits = b_检索.search_fts(question, limit=5)
        used = "全文索引"
        if not hits:
            hits = b_检索.search(question, limit=5,
                                 min_quality=70 if gate == "质量分 ≥ 70" else 0,
                                 only_meta=(gate == "只看有元数据的"))
            used = "LIKE 兜底"
        st.session_state["kw_result"] = {
            "question": question, "hits": hits,
            "used": used, "elapsed": time.time() - t0,
        }

    saved = st.session_state.get("kw_result")
    if not saved:
        return

    hits = saved["hits"]
    st.caption("查询：%s ｜ 方式：%s ｜ 耗时 %.2f 秒 ｜ 命中 %d"
               % (saved["question"], saved["used"], saved["elapsed"], len(hits)))
    if not hits:
        st.info("没找到。试试减少关键词，或换同义词。")
        return

    for i, hit in enumerate(hits, start=1):
        rec = hit.get("record") or {}
        st.markdown("**%d. 来自 `%s`**" % (i, hit["table"]))
        if lang == "原文":
            st.json(rec, expanded=(i == 1))
            continue
        key = "trk_%d_%s_%s" % (i, lang, hit["table"])
        if st.button("翻译成%s" % lang, key="btnk_" + key):
            with st.spinner("翻译中（首次较慢）…"):
                from framework_b import b_翻译

                st.session_state[key] = b_翻译.record(rec, "zh" if lang == "中文" else "en")
        if st.session_state.get(key):
            st.json(st.session_state[key], expanded=(i == 1))
            if st.button("恢复原文", key="rstk_" + key):
                st.session_state[key] = None
                st.rerun()
        else:
            st.json(rec, expanded=(i == 1))


# ---------------------------------------------------------------------------
# 病历总结
# ---------------------------------------------------------------------------
def _page_summary() -> None:
    st.caption("粘一份病历或上传照片 → 输出「主诉 / 现病史 / 既往史 / 关键检查 / 诊断 / 处理」六段。"
               "只根据原文提炼，不推测、不给治疗建议。")

    # 总结默认走主模型：本地 4B 要 20~60 秒，主模型 2~5 秒
    key_ok = b_总结.has_key()
    if key_ok:
        st.caption("当前走**主模型**（几秒出结果）。想换回本地模型，把 Key 清掉即可。")
    else:
        st.warning("病历总结现在走**主模型**（DeepSeek 等），需要先配 Key。"
                   "到「自检」标签页填 Key（或 .env 里写 MY_LLM_KEY=…），2~5 秒就能出结果。")
        st.caption("没有 Key 也能凑合：勾选下面用本地模型，约 20~60 秒。")
    slow_local = (not key_ok) and st.checkbox("没有 Key，先用本地模型（慢）", value=False)

    mode = st.radio("输入方式", ["粘贴文字", "上传图片"], horizontal=True)

    text = ""
    blocked = (not key_ok) and (not slow_local)
    if mode == "粘贴文字":
        text = st.text_area(
            "病历原文",
            height=220,
            placeholder=(
                "整段粘进来就行，不需要按固定格式。\n"
                "例如：患者男，67 岁。反复咳嗽咳痰 3 年，加重伴发热 2 天。\n"
                "3 天前受凉后咳黄痰，最高 38.9℃，无胸痛。高血压 10 年，吸烟 40 年。\n"
                "双肺可闻及湿啰音，胸片示右下肺片状影。诊断社区获得性肺炎，予抗感染。"
            ),
        )
        go = st.button("生成总结", type="primary",
                       disabled=blocked or len(text.strip()) < 20)
        image = None
    else:
        image = st.file_uploader("上传病历照片", type=["png", "jpg", "jpeg", "webp"])
        go = st.button("识别并总结", type="primary", disabled=blocked or image is None)
        if not key_ok:
            st.caption("注：读图（OCR）只能用本地多模态模型，这一步本身就慢；"
                       "配了 Key 的话后面的六段总结会快很多。")

    if not go:
        return

    if mode == "上传图片" and image is not None:
        tmp = ROOT / "data" / ("_upload_%s" % image.name)
        tmp.write_bytes(image.getbuffer())
        with st.spinner("读图中（本地多模态模型，约 10~40 秒）…"):
            try:
                text = b_总结.read_image(str(tmp))
            except Exception as exc:
                st.error("读图失败：%s" % exc)
                return
        with st.expander("图片转写（先核对有没有读错）", expanded=True):
            st.text(text)
        if len(text.strip()) < 20:
            st.warning("转写内容太少，可能图片模糊。")
            return

    spinner = "主模型提炼中（约 2~5 秒）…" if (key_ok and not slow_local) else "本地模型提炼中（约 20~60 秒）…"
    with st.spinner(spinner):
        try:
            result = b_总结.summarize(text, use_master=(key_ok and not slow_local))
        except Exception as exc:
            st.error("总结失败：%s" % exc)
            return
    st.markdown("### 总结")
    st.write(result)


# ---------------------------------------------------------------------------
# 自检 + 设置
# ---------------------------------------------------------------------------
def _page_health() -> None:
    with st.spinner("检查中…"):
        h = b_核心.health()
    for label, key in (("数据库", "db"), ("本地模型", "local"), ("主模型", "master")):
        item = h.get(key) or {}
        _light(label, bool(item.get("ok")), str(item.get("detail", "?")))

    st.divider()
    st.markdown("### 主模型 Key")
    st.caption("「病历总结」默认走主模型，需要这个 Key（2~5 秒出结果）；"
               "不配也能用本地模型总结，只是慢（20~60 秒）。"
               "检索、关键词、相似病例、翻译全部走本地，不依赖 Key。")

    from framework_b import b_配置

    current = b_配置.get_key()
    _light("当前 Key", bool(current), b_配置.mask(current))
    key = st.text_input("填写 Key", type="password", placeholder="sk-…（留空不改）")
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        save = st.button("保存", type="primary", disabled=not key.strip())
    with b2:
        test = st.button("测试连接")
    with b3:
        clear = st.button("清除 Key")
    if save and b_配置.set_key(key):
        st.success("已保存（写入 .env，与框架 A 共用）")
    if test:
        ok, msg = b_配置.test_key(key or current)
        (st.success if ok else st.error)(msg)
    if clear:
        b_配置.set_key("")
        st.info("已清除")


def main() -> None:
    st.title("🔎 Framework B · 检索应用")
    st.caption("只读数据库、对外回答问题。数据由 Framework A 生产。")

    t1, t2, t3, t4, t5 = st.tabs(["概览", "相似病例", "关键词检索", "病历总结", "自检"])
    with t1:
        _page_overview()
    with t2:
        _page_similar()
    with t3:
        _page_search()
    with t4:
        _page_summary()
    with t5:
        _page_health()


if __name__ == "__main__":
    main()
