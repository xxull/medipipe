# -*- coding: utf-8 -*-
"""
eICU 层级诊断名的分段翻译（segment glossary）
=========================================================================
eICU 的诊断长这样：

    pulmonary|respiratory failure|acute respiratory distress

三段分别是"系统|类别|具体病"。整句翻译模型不一定对，
但**逐段查词表**拼起来又快又稳。
"""
SEGMENTS = {
    # 系统
    "pulmonary": "呼吸系统",
    "cardiovascular": "心血管",
    "renal": "肾脏",
    "endocrine": "内分泌",
    "gastrointestinal": "消化系统",
    "neurologic": "神经系统",
    "hematologic": "血液",
    "musculoskeletal": "骨骼肌肉",
    "integumentary": "皮肤",
    "genitourinary": "泌尿生殖",
    "psychiatric": "精神",
    "trauma": "创伤",
    "infectious diseases": "感染",
    "toxicology": "中毒",
    "transplant": "移植",
    "pain": "疼痛",
    "surgical": "外科",
    # 类别
    "respiratory failure": "呼吸衰竭",
    "disorders of the airways": "气道疾病",
    "pulmonary infections": "肺部感染",
    "pulmonary embolism": "肺栓塞",
    "pleural effusion": "胸腔积液",
    "vascular disorders": "血管疾病",
    "shock / hypotension": "休克/低血压",
    "arrhythmia": "心律失常",
    "ischemic heart disease": "缺血性心脏病",
    "congestive heart failure": "充血性心力衰竭",
    "disorder of kidney": "肾脏疾病",
    "glucose metabolism": "糖代谢",
    "thyroid": "甲状腺",
    "sepsis": "脓毒症",
    "bleeding": "出血",
    "obstruction": "梗阻",
    "infection": "感染",
    # 具体病
    "acute respiratory distress": "急性呼吸窘迫",
    "acute respiratory failure": "急性呼吸衰竭",
    "acute respiratory distress syndrome": "急性呼吸窘迫综合征",
    "pneumonia": "肺炎",
    "asthma": "哮喘",
    "copd": "慢阻肺",
    "chronic obstructive pulmonary disease": "慢性阻塞性肺疾病",
    "pneumothorax": "气胸",
    "hypertension": "高血压",
    "hypotension": "低血压",
    "sepsis, pulmonary": "肺部脓毒症",
    "sepsis, renal/uti (including bladder)": "泌尿系脓毒症",
    "acute renal failure": "急性肾衰竭",
    "chronic renal failure": "慢性肾衰竭",
    "diabetes mellitus": "糖尿病",
    "diabetic ketoacidosis": "糖尿病酮症酸中毒",
    "chest pain, unspecified": "未特指的胸痛",
    "hypoxemia": "低氧血症",
    "hypercapnia": "高碳酸血症",
    "myocardial infarction": "心肌梗死",
    "atrial fibrillation": "心房颤动",
    # 补：实测里没翻出来的
    "aspiration": "吸入",
    "acute copd exacerbation": "慢阻肺急性加重",
    "copd exacerbation": "慢阻肺急性加重",
    "pulmonary infections": "肺部感染",
    "disorders of the airways": "气道疾病",
    "respiratory failure": "呼吸衰竭",
    "shortness of breath": "呼吸困难",
    "dyspnea": "呼吸困难",
    "fever": "发热",
    "nausea": "恶心",
    "vomiting": "呕吐",
    "abdominal pain": "腹痛",
    "diarrhea": "腹泻",
    "constipation": "便秘",
    "syncope": "晕厥",
    "seizure": "癫痫发作",
    "delirium": "谵妄",
    "anemia": "贫血",
    "thrombocytopenia": "血小板减少",
    "leukocytosis": "白细胞增多",
    "hyperglycemia": "高血糖",
    "hypoglycemia": "低血糖",
    "acidosis": "酸中毒",
    "alkalosis": "碱中毒",
}



def translate_hier(name: str) -> str:
    """把 'a|b|c' 逐段查表拼成中文；查不到的段保留原文。"""
    if "|" not in name:
        return name
    parts = [p.strip() for p in name.split("|")]
    out = []
    for p in parts:
        out.append(SEGMENTS.get(p.lower(), SEGMENTS.get(p, p)))
    # 去掉重复（"呼吸系统|呼吸衰竭" 不必写成 "呼吸系统/呼吸衰竭" 两遍同义）
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return "/".join(uniq)
