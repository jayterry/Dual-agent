# DAI 風險評分 ML 資料目錄

| 檔案 | 說明 |
|------|------|
| `labels.example.jsonl` | 標註格式範例（可提交 git） |
| `labels_synthetic.jsonl` | 模擬標註（`bootstrap_synthetic_labels.py` 產生，約 150+ 筆） |
| `features_synthetic.csv` | 特徵矩陣（`export_risk_features.py` 產生） |

## 快速開始

```bash
cd Dual-agent
python scripts/bootstrap_synthetic_labels.py
python scripts/export_risk_features.py
python scripts/train_risk_lr.py
```

模型輸出：`data/risk_models/lr_v0/model.pkl`

> 模擬標籤僅供管線驗證與初始係數參考；有真實人工標註後請重新訓練。
