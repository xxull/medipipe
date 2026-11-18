# data/ 目录说明

**库和向量不进版本库。** 这些都能用 `tools/` 下的脚本重新生成，
体积可能到几十 GB（本地实测 43 GB 数据库 + 6 GB 原始数据集）。

## 唯一进仓库的：可自由分发的小数据

| 路径 | 条数 | 内容 | 许可 |
|---|---|---|---|
| `样例数据/病例样例.jsonl` | 204 | 合成病例，12 个科室 | 本项目生成 |
| `样例数据/症状样例.jsonl` | 53 | 各科室症状词表 | 本项目生成 |
| `开放数据/药品_openfda.jsonl` | 1000 | 药品说明书（品牌名 / 通用名 / 适应症 / 用法 / 警示） | CC0-1.0 |
| `开放数据/问答_medquad.jsonl` | 2000 | 医学问答（患者教育） | CC BY 4.0 |

合成病例只用于跑通界面与检索链路：症状、诊断、用药是随机组合，
年龄 / 性别与病种**不做医学合理性配对**。要看真实分布，请用自己授权的数据。

MedQuAD 数据来自 <https://github.com/abachaa/MedQuAD>，按 CC BY 4.0 使用，
分发时请保留 `data/开放数据/问答_medquad.jsonl` 每行里的 `license` 字段和署名。

## 会被自动排除的内容

| 路径 | 说明 |
|---|---|
| `records.db` | SQLite 主库（药品 + 病历 + 病例库 + 全文索引） |
| `case_vectors.bin` | 向量矩阵（float32，每行 1024 维） |
| `case_ids.jsonl` | 向量对应的病例 ID |
| `hf/` | 从 HuggingFace 下载的原始数据集 |
| `mimic_demo/` | MIMIC demo CSV |
| `cmb/` | CMB 中文医学数据集 |
| `hf_token.txt` | HuggingFace token（**密钥，绝对不能提交**） |
| `*.log` / `*日志*.txt` | 运行日志 |

## 怎么重建

```bash
# 1) 合成病例 + 症状词表
python tools/生成样例数据.py
python tools/导入样例数据.py          # 建库 + 建向量

# 2) 开放数据（药品 + 问答）
python tools/下载开放数据.py           # 需要联网；仓库已带一份，可跳过
python tools/导入开放数据.py           # 建表 + 全文索引

# 3) 加公开病历（需自行申请，遵守协议）
python tools/从zip导入.py --zip MIMIC-IV.zip --prefix miv
python tools/建病例库.py 100000

# 4) 建索引与向量
python tools/建搜索索引.py
python tools/建向量.py
```

## 合规提醒

- **MIMIC-IV / eICU**：使用协议禁止再分发。不要把这些数据（包括由它们派生的
  病例库、向量）提交到任何公开仓库。
- **中国医药信息查询平台（dayi）**：内容有版权，`tools/爬dayi.py` 抓到的数据
  只能本地研究，不要随仓库或产品分发。
- **openFDA**：公共领域 / CC0，可自由使用。
- **MedQuAD**：CC BY 4.0，可再分发，但要署名。

要分享请用合成数据，或者只分享代码。
