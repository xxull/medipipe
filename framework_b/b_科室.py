# -*- coding: utf-8 -*-
"""
疾病 → 科室 分类（b_科室）
=========================================================================
为什么按科室分？
-------------------------------------------------------------------------
    同一个"高血压"，在心内科和肾内科语境下含义不同。
    先按科室收窄，再在科室内比相似度，指向性更准、噪音更少。

分类规则
-------------------------------------------------------------------------
    关键词匹配（英文 ICD 标题 + 中文术语）。一个病名可能命中多个科室
    （比如"糖尿病肾病"既是内分泌也是肾内），这时：

        * 第一个命中的是"主科室"
        * 命中的都记进 departments（用于多科室统计）

特殊病库
-------------------------------------------------------------------------
    有些病本身就是多系统/多部位的（比如系统性红斑狼疮、结节病、血管炎），
    强行归到一个科室会失真。这类单独进 SPECIAL。
=========================================================================
"""

from __future__ import annotations

from typing import Dict, List, Tuple

#: 科室 → 关键词（小写匹配；英文为主，兼顾中文）
DEPARTMENT_KEYWORDS: Dict[str, List[str]] = {
    "心内科": [
        "hypertension", "hypertensive", "coronary", "myocardial", "angina",
        "heart failure", "atrial fibrillation", "arrhythmia", "cardiac",
        "cardiomyopathy", "valvular", "pericard", "tachycardia", "bradycardia",
        "heart", "stent", "cabg", "高血压", "冠心病", "心衰", "心律失常", "房颤",
    ],
    "呼吸内科": [
        "pneumonia", "copd", "asthma", "bronchitis", "emphysema", "pleural",
        "pneumothorax", "respiratory failure", "hypoxemia", "pulmonary",
        "tuberculosis", "sleep apnea", "呼吸衰竭", "肺炎", "哮喘", "慢阻肺", "肺",
    ],
    "消化内科": [
        "gastro", "esophag", "reflux", "gastritis", "ulcer", "hepatitis",
        "cirrhosis", "pancreatitis", "cholecystitis", "cholangitis", "colitis",
        "crohn", "bowel", "diarrhea", "constipation", "abdominal pain",
        "gastrointestinal", "胃", "肠", "肝", "胰", "消化",
    ],
    "神经内科": [
        "stroke", "cerebrovascular", "cva", "seizure", "epilep", "migraine",
        "dementia", "alzheimer", "parkinson", "neuropathy", "myasthenia",
        "meningitis", "encephalitis", "headache", "syncope", "vertigo",
        "脑", "癫痫", "头痛", "眩晕", "神经",
    ],
    "肾内科": [
        "renal", "kidney", "nephritis", "nephrotic", "dialysis", "hemodialysis",
        "electrolyte", "hyperkalemia", "hyponatremia", "proteinuria",
        "肾", "透析", "电解质",
    ],
    "内分泌科": [
        "diabetes", "diabetic", "thyroid", "hypothyroid", "hyperthyroid",
        "obesity", "hyperlipidemia", "hypercholesterolemia", "ketoacidosis",
        "adrenal", "pituitary", "osteoporosis", "gout", "糖尿病", "甲状腺",
        "肥胖", "血脂", "痛风",
    ],
    "血液科": [
        "anemia", "thrombocytopenia", "thrombosis", "leukemia", "lymphoma",
        "myeloma", "coagulation", "hemorrhage", "neutropenia", "pancytopenia",
        "贫血", "血小板", "白血病", "淋巴瘤",
    ],
    "感染科": [
        "sepsis", "septic", "infection", "bacteremia", "viremia", "covid",
        "influenza", "hiv", "hepatitis b", "hepatitis c", "abscess", "cellulitis",
        "脓毒", "感染", "败血",
    ],
    "风湿免疫科": [
        "lupus", "rheumatoid", "vasculitis", "scleroderma", "sjogren",
        "psoriatic", "ankylosing", "polymyalgia", "sarcoid", "amyloid",
        "红斑狼疮", "类风湿", "血管炎", "干燥",
    ],
    "肿瘤科": [
        "neoplasm", "carcinoma", "malignant", "metasta", "tumor", "cancer",
        "chemotherapy", "radiotherapy", "palliative", "癌", "肿瘤", "化疗",
    ],
    "普外科": [
        "appendicitis", "hernia", "cholelithiasis", "gallstone", "bowel obstruction",
        "peritonitis", "diverticulitis", "hemorrhoid", "fistula", "laparotomy",
        "阑尾", "疝", "胆囊", "肠梗阻", "腹膜炎",
    ],
    "骨科": [
        "fracture", "osteoarthritis", "arthroplasty", "spondyl", "disc",
        "sciatica", "tendon", "ligament", "bone", "joint", "骨折", "关节", "腰椎",
    ],
    "泌尿外科": [
        "prostate", "bladder", "urolithiasis", "hydronephrosis", "nephrostomy",
        "cystitis", "urinary retention", "前列腺", "膀胱", "结石",
    ],
    "神经外科": [
        "subdural", "subarachnoid", "intracranial hemorrhage", "hydrocephalus",
        "brain tumor", "craniotomy", "aneurysm", "颅", "脑出血", "动脉瘤",
    ],
    "心胸外科": [
        "cabg", "valve replacement", "thoracotomy", "lobectomy", "aortic",
        "bypass grafting", "纵隔", "搭桥", "瓣膜",
    ],
    "妇产科": [
        "pregnan", "delivery", "cesarean", "obstetric", "preeclamp", "eclampsia",
        "labor", "uterine", "ovarian", "妊娠", "分娩", "产后", "卵巢", "子宫",
    ],
    "儿科": ["neonat", "infant", "child", "pediatric", "新生儿", "儿童"],
    "眼科": [
        "retina", "retinal", "glaucoma", "cataract", "macular", "optic",
        "conjunctiv", "keratitis", "uveitis", "vitreous", "眼", "视网膜", "青光眼",
        "白内障", "黄斑",
    ],
    "耳鼻喉科": [
        "otitis", "sinusitis", "tonsillitis", "laryngitis", "hearing", "epistaxis",
        "nasal", "pharyng", "耳", "鼻", "咽", "喉",
    ],
    "皮肤科": [
        "dermatitis", "eczema", "psoriasis", "urticaria", "cellulitis", "rash",
        "skin", "wound", "皮炎", "湿疹", "皮疹", "皮肤",
    ],
    "精神科": [
        "depress", "anxiety", "schizophren", "bipolar", "psychosis", "delirium",
        "substance", "alcohol", "opioid", "抑郁", "焦虑", "精神", "谵妄", "成瘾",
    ],
    "急诊重症": [
        "cardiac arrest", "shock", "trauma", "poisoning", "overdose", "burns",
        "resuscitation", "coma", "multi-organ", "骤停", "休克", "中毒", "创伤",
    ],
    "康复科": ["rehabilitation", "physical therapy", "康复"],
    "口腔科": ["dental", "tooth", "periodontal", "口腔", "牙"],
}

#: 多系统/多部位疾病：不强行归科，单独进特殊病库
SPECIAL: List[Tuple[str, str]] = [
    ("lupus", "系统性红斑狼疮（多系统）"),
    ("sarcoid", "结节病（多系统）"),
    ("vasculitis", "血管炎（多血管）"),
    ("amyloid", "淀粉样变性（多器官）"),
    ("scleroderma", "系统性硬化症（多系统）"),
    ("sjogren", "干燥综合征（多腺体）"),
    ("antiphospholipid", "抗磷脂综合征（多血管）"),
    ("multiple sclerosis", "多发性硬化（中枢多灶）"),
    ("myasthenia", "重症肌无力（神经肌肉）"),
    ("endocarditis", "感染性心内膜炎（多系统）"),
    ("tuberculosis", "结核病（可多器官）"),
    ("covid", "新冠感染（多系统）"),
    ("sepsis", "脓毒症（多器官）"),
    ("metasta", "转移性肿瘤（多部位）"),
    ("polytrauma", "多发伤"),
]


_LABELS: Dict[str, str] = {}
_LABELS_LOADED = False


def _load_labels() -> Dict[str, str]:
    """
    加载 Huatuo 学出来的"疾病 → 科室"对照（disease_dept 表）。

    这是**真实标注投票**的结果，比关键词规则准，所以优先用它。
    表不存在时返回空，自动退回关键词。
    """
    global _LABELS, _LABELS_LOADED
    if _LABELS_LOADED:
        return _LABELS
    _LABELS_LOADED = True
    try:
        import sqlite3
        from pathlib import Path

        db = Path(__file__).resolve().parent.parent / "data" / "records.db"
        conn = sqlite3.connect(str(db), timeout=30)
        try:
            _LABELS = dict(conn.execute("SELECT disease, dept FROM disease_dept"))
        finally:
            conn.close()
    except Exception:
        _LABELS = {}
    return _LABELS


def classify(name: str) -> Tuple[str, List[str], str]:
    """
    返回 (主科室, 所有命中科室, 特殊病说明)。

    优先级：
        1. Huatuo 真实标注（disease_dept）
        2. 特殊病库（多系统疾病，归科会失真）
        3. 关键词规则
    """
    text = (name or "").strip()

    # 1. 真实标注
    labels = _load_labels()
    if text in labels:
        return labels[text], [labels[text]], ""

    low = text.lower()

    # 2. 特殊病
    for key, desc in SPECIAL:
        if key in low:
            return "特殊病库", ["特殊病库"], desc

    # 3. 关键词
    hits = []
    for dept, keywords in DEPARTMENT_KEYWORDS.items():
        if any(k in low for k in keywords):
            hits.append(dept)

    if not hits:
        return "未分类", [], ""
    return hits[0], hits, ""


def group_by_department(diseases: List[Tuple[str, int, float]]) -> List[Dict]:
    """
    把"疾病统计"按科室汇总。

    输入：[(英文原名, 次数, 占比), ...]
        —— 必须用英文原名！科室关键词是英文的；
           传中文名会全部落到"未分类"。
    输出：[{"科室": "呼吸内科", "次数": 12, "疾病": [...]}, ...]
    """
    buckets: Dict[str, Dict] = {}
    for name, n, p in diseases:
        dept, hits, note = classify(name)
        key = dept
        if key not in buckets:
            buckets[key] = {"科室": key, "次数": 0, "疾病": [], "说明": note}
        buckets[key]["次数"] += n
        buckets[key]["疾病"].append({"name": name, "n": n, "p": p})
        # 一个病命中多个科室时，次要科室只记次数，不重复列疾病
        for extra in hits[1:]:
            if extra not in buckets:
                buckets[extra] = {"科室": extra, "次数": 0, "疾病": []}
            buckets[extra]["次数"] += n

    out = sorted(buckets.values(), key=lambda x: -x["次数"])
    return out


if __name__ == "__main__":
    import sys

    samples = sys.argv[1:] or [
        "Pneumonia, bacterial",
        "Diabetic ketoacidosis",
        "Systemic lupus erythematosus",
        "Acute kidney failure, unspecified",
        "pulmonary|respiratory failure|acute respiratory distress",
        "Atrial fibrillation",
        "Major depressive disorder, single episode, unspecified",
        "Retinal detachment",
    ]
    for s in samples:
        dept, hits, note = classify(s)
        print("%-52s → %-8s %s %s" % (s[:52], dept, hits[1:] if len(hits) > 1 else "", note))
