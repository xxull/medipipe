# data/ 目录说明

**这个目录不进版本库。** 里面的东西都能用 `tools/` 下的脚本重新生成，
而且体积可能到几十 GB（本地实测 43 GB 数据库 + 6 GB 原始数据集）。

## 会被自动排除的内容

| 路径 | 说明 |
|---|---|
| `data/records.db` | SQLite 主库（药品 + 病历 + 病例库 + 全文索引） |
| `data/case_vectors.bin` | 向量矩阵（float32，每行 1024 维） |
| `data/case_ids.jsonl` | 向量对应的病例 ID |
| `data/hf/` | 从 HuggingFace 下载的原始数据集 |
| `data/mimic_demo/` | MIMIC demo CSV |
| `data/cmb/` | CMB 中文医学数据集 |
| `data/hf_token.txt` | HuggingFace token（**密钥，绝对不能提交**） |
| `data/*.log` / `*日志*.txt` | 运行日志 |

## 唯一会进仓库的

`data/样例数据/病例样例.jsonl` —— 204 条**合成**病例，覆盖 12 个科室，
由 `tools/生成样例数据.py` 生成，不含真实个人信息。

## 怎么重建

```bash
# 最小可用（只有样例数据）
python tools/生成样例数据.py
python tools/导入样例数据.py

# 加药品数据（openFDA）
python tools/跑药品.py 1000

# 加公开病历（需自行申请 MIMIC/eICU，遵守其协议）
python tools/从zip导入.py --zip <数据集.zip> --prefix miv
python tools/建病例库.py 100000

# 建全文索引与向量
python tools/建搜索索引.py
python tools/建向量.py
```

## 合规提醒

MIMIC-IV 与 eICU 的使用协议**禁止再分发**。不要把这些数据（包括由它们
派生的病例库、向量）提交到任何公开仓库。要分享请用合成数据。
