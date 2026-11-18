# -*- coding: utf-8 -*-
"""
生成公开可用的样例数据（合成病例）
=========================================================================
为什么不用真实病历？
-------------------------------------------------------------------------
    MIMIC / eICU 都有使用协议（禁止再分发），Huatuo 等也有各自的许可。
    把真实病历塞进公开仓库会有版权和合规风险。

    所以这里**生成合成病例**：结构、字段、科室分布都贴近真实，
    但内容由程序拼出来，不含任何真实个人信息，可以随便传播。

生成内容
-------------------------------------------------------------------------
    data/样例数据/病例样例.jsonl   200 条，覆盖 12 个科室
    data/样例数据/药品样例.jsonl   50 条药品（取自 openFDA 公共领域字段的改写）

用法
-------------------------------------------------------------------------
    python tools\生成样例数据.py
=========================================================================
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "样例数据"

#: 科室 → 症状片段、诊断、常用药
DEPTS = {
    "呼吸内科": {
        "symptoms": ["咳嗽咳痰", "发热", "胸闷", "气短", "咯血"],
        "diseases": ["社区获得性肺炎", "慢性阻塞性肺疾病急性加重", "支气管哮喘", "支气管扩张"],
        "drugs": ["阿莫西林克拉维酸", "左氧氟沙星", "布地奈德", "沙丁胺醇", "氨溴索"],
    },
    "心内科": {
        "symptoms": ["胸痛", "心悸", "活动后气促", "下肢水肿", "晕厥"],
        "diseases": ["冠状动脉粥样硬化性心脏病", "心房颤动", "慢性心力衰竭", "高血压性心脏病"],
        "drugs": ["阿司匹林", "阿托伐他汀", "美托洛尔", "呋塞米", "硝酸甘油"],
    },
    "消化内科": {
        "symptoms": ["上腹痛", "反酸", "恶心呕吐", "腹胀", "黑便"],
        "diseases": ["胃食管反流病", "消化性溃疡", "急性胰腺炎", "慢性胃炎"],
        "drugs": ["奥美拉唑", "铝碳酸镁", "莫沙必利", "生长抑素", "蒙脱石散"],
    },
    "神经内科": {
        "symptoms": ["头痛", "眩晕", "肢体无力", "言语不清", "抽搐"],
        "diseases": ["急性脑梗死", "偏头痛", "癫痫", "短暂性脑缺血发作"],
        "drugs": ["阿司匹林", "氯吡格雷", "阿托伐他汀", "甘露醇", "丙戊酸钠"],
    },
    "内分泌科": {
        "symptoms": ["多饮多尿", "体重下降", "乏力", "怕冷", "心慌手抖"],
        "diseases": ["2 型糖尿病", "糖尿病酮症酸中毒", "甲状腺功能亢进症", "甲状腺功能减退症"],
        "drugs": ["二甲双胍", "胰岛素", "甲巯咪唑", "左甲状腺素钠", "格列美脲"],
    },
    "肾内科": {
        "symptoms": ["水肿", "尿量减少", "泡沫尿", "腰痛", "乏力"],
        "diseases": ["慢性肾脏病", "急性肾损伤", "肾病综合征", "高钾血症"],
        "drugs": ["呋塞米", "碳酸钙", "复方α酮酸", "厄贝沙坦", "聚苯乙烯磺酸钙"],
    },
    "血液科": {
        "symptoms": ["面色苍白", "皮下瘀斑", "发热", "乏力", "淋巴结肿大"],
        "diseases": ["缺铁性贫血", "免疫性血小板减少症", "急性髓系白血病", "淋巴瘤"],
        "drugs": ["琥珀酸亚铁", "叶酸", "泼尼松", "血小板生成素", "利妥昔单抗"],
    },
    "感染科": {
        "symptoms": ["高热", "寒战", "乏力", "皮疹", "腹泻"],
        "diseases": ["脓毒症", "病毒性肝炎", "感染性腹泻", "泌尿系感染"],
        "drugs": ["头孢曲松", "莫西沙星", "奥司他韦", "恩替卡韦", "万古霉素"],
    },
    "骨科": {
        "symptoms": ["腰腿痛", "关节肿痛", "活动受限", "外伤后疼痛", "下肢麻木"],
        "diseases": ["腰椎间盘突出症", "膝关节骨关节炎", "股骨颈骨折", "颈椎病"],
        "drugs": ["塞来昔布", "氨基葡萄糖", "甲钴胺", "钙尔奇", "独活寄生丸"],
    },
    "泌尿外科": {
        "symptoms": ["尿频尿急", "排尿困难", "血尿", "腰腹绞痛", "尿痛"],
        "diseases": ["前列腺增生", "输尿管结石", "膀胱炎", "肾结石"],
        "drugs": ["坦索罗辛", "左氧氟沙星", "双氯芬酸钠", "枸橼酸氢钾钠", "非那雄胺"],
    },
    "妇科": {
        "symptoms": ["下腹痛", "月经不规律", "白带异常", "阴道出血", "停经"],
        "diseases": ["盆腔炎", "子宫肌瘤", "异位妊娠", "多囊卵巢综合征"],
        "drugs": ["甲硝唑", "头孢呋辛", "米非司酮", "屈螺酮炔雌醇", "桂枝茯苓胶囊"],
    },
    "儿科": {
        "symptoms": ["发热", "咳嗽", "腹泻", "食欲差", "皮疹"],
        "diseases": ["小儿肺炎", "手足口病", "急性喉炎", "婴幼儿腹泻"],
        "drugs": ["阿莫西林", "布洛芬混悬液", "蒙脱石散", "口服补液盐", "利巴韦林"],
    },
}

AGES = [(0, 17, "0-17"), (18, 44, "18-44"), (45, 64, "45-64"), (65, 90, "65+")]


def main() -> int:
    random.seed(20260101)
    OUT.mkdir(parents=True, exist_ok=True)

    rows = []
    n = 0
    for dept, info in DEPTS.items():
        for _ in range(17):          # 每个科室 17 条 ≈ 204 条
            n += 1
            lo, hi, band = random.choice(AGES)
            age = random.randint(max(lo, 1), hi)   # 不出现“0岁”，免得像错数据
            sx = random.sample(info["symptoms"], k=random.randint(2, 3))
            disease = random.choice(info["diseases"])
            drugs = random.sample(info["drugs"], k=random.randint(1, 3))
            duration = random.choice(["1 天", "3 天", "1 周", "2 周", "1 个月"])
            history = random.choice([
                "无特殊", "高血压 10 年", "2 型糖尿病 5 年", "吸烟 20 年",
                "既往体健", "冠心病史", "慢性肾病 3 期",
            ])
            gender = random.choice(["男", "女"])

            rows.append({
                "case_id": "sample_%03d" % n,
                "source": "sample",
                "dept": dept,
                "age": age,
                "age_band": band,
                "gender": gender,
                "symptom": "、".join(sx),
                "duration": duration,
                "history": history,
                "diseases": [disease],
                "drugs": drugs,
                "text": "症状：%s %s。患者%s，%d岁。既往史：%s。诊断：%s。用药：%s。" % (
                    "、".join(sx), duration, gender, age, history, disease, "、".join(drugs)),
                "license": "本文件由脚本生成，不含真实个人信息，可自由使用",
            })

    case_file = OUT / "病例样例.jsonl"
    with open(case_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print("已生成 %d 条合成病例 → %s" % (len(rows), case_file))
    print("\n科室分布：")
    from collections import Counter

    for d, c in Counter(r["dept"] for r in rows).most_common():
        print("  %-8s %d" % (d, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
