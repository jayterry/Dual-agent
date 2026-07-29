# DAI 風險評分 ML 資料目錄

| 檔案 | 說明 |
|------|------|
| `labels.example.jsonl` | 標註格式範例（可提交 git） |
| `labels_synthetic.jsonl` | 舊版混合模板標註（`bootstrap_synthetic_labels.py`） |
| `features_synthetic.csv` | 舊版特徵矩陣 |
| `labels_llm_bank_600.jsonl` | **銀行面** 600 筆（300 scam + 300 benign） |
| `features_llm_bank_600.csv` | 銀行面特徵矩陣 |

## 銀行面 Dataset（本輪）

```bash
cd Dual-agent

# 離線／smoke：模板槽位擴寫（不需 Ollama）
python scripts/generate_llm_risk_labels.py --domain bank --fallback-templates

# 正式：本機 Ollama LLM 生成（不足自動以模板補齊）
python scripts/generate_llm_risk_labels.py --domain bank --n-scam 300 --n-benign 300

# 小量驗證
python scripts/generate_llm_risk_labels.py --domain bank --dry-run --fallback-templates

# 匯出特徵（機器層；可設 DAI_SEMANTIC_LLM=0 加速）
set DAI_SEMANTIC_LLM=0
python scripts/export_risk_features.py ^
  --labels data/risk_training/labels_llm_bank_600.jsonl ^
  --out data/risk_training/features_llm_bank_600.csv
```

Scam 桶：`bank_otp` / `bank_password` / `bank_card` / `bank_phish_url` / `bank_transfer` / `bank_loan`  
Benign 桶：`bank_official_notify` / `bank_app_alert` / `bank_work_assign`

## 訓練銀行面 LR（含視覺化）

```bash
# 梯度下降（會產出 loss 曲線 + ROC + 係數圖）
python scripts/train_risk_lr.py ^
  --features data/risk_training/features_llm_bank_600.csv ^
  --out data/risk_models/lr_bank_v0_gd ^
  --solver gd --epochs 1500

# 圖檔在 data/risk_models/lr_bank_v0_gd/eval_plots/
# - gd_loss_curve.png
# - roc_curve.png
# - answer_vs_prediction_dist.png
# - label_vs_ml_proba.png
# - lr_coefficients_top.png
```

## 舊版快速開始

```bash
python scripts/bootstrap_synthetic_labels.py
python scripts/export_risk_features.py
python scripts/train_risk_lr.py
```

模型輸出：`data/risk_models/lr_v0/model.pkl`

> 合成標籤僅供管線驗證與初始係數參考；有真實人工標註後請重新訓練。
