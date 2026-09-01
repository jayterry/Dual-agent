# DAI 與桌面 ML 對照

> 最後更新：2026-08-31  
> 狀態：**已接線** — Dual-agent 內嵌 `dual_agent/dai/fraud_dual/`，模型在 `data/fraud_dual_models/`  
> 桌面引擎路徑：`C:\Users\labpc\Desktop\ml`（研究／訓練源頭）  
> 相關：[RISK_SCORING.md](./RISK_SCORING.md)、[專案進度與目標.md](./專案進度與目標.md)、[DAI_ML風險校準.md](./DAI_ML風險校準.md)（舊 bank LR，legacy）

---

## 定案

1. **桌面 `ml` 專案 = DAI 詐騙評分主演算法**，不是 UEBA 旁路、也不是 breakdown 加分項。
2. **已覆蓋**舊主評分：legacy 加權融合、`DAI_RISK_FUSION_MODE=ml_lr`、以及「對使用者只展示單一 `risk_score`」契約（主路徑改為雙分）。
3. **建圖／使用者資訊**（`age_band`、`occupation`、`relation_type`、`channel`、`primary_apps`、選填 `invest_exp`）由 **CAI 或 APP 介面**供給。
4. **展示**：並列 `threat_score` + `context_score`（0–1，可×100 顯示）；**不**強壓成單一 risk。
5. **`allow`／`warn`／`block`**：閘道分 `max(threat, context)` + 雙分政策；高 threat 硬擋優先於低 context。
6. 線上主判決用 **Path A（Result_A）**；Path B（純 LLM）為對照，產品預設可開（`DAI_DUAL_PATH_B`）。

---

## 誰退誰留

| 現行 DAI | 覆蓋後 |
|----------|--------|
| `fuse_risk_score_weighted`／單一 `risk_score` | 退役主判決；可暫留 `legacy` 回滾 |
| `fuse_risk_score_ml`（`ml_lr`） | 退役主判決（≠ 桌面 ml） |
| rules Tier 90／TI hard guard | 可保留：政策表強制 `block` |
| UEBA `user_db` | 不再替代 Context；信任網域仍用於舊管線 |
| 桌面 Path A | **主分數來源**（內嵌 `fraud_dual`） |
| 桌面 Path B | 對照；產品可開 |
| Narrator | 解釋 Path A，不改分數 |

**勿混淆**：[DAI_ML風險校準.md](./DAI_ML風險校準.md) 的 bank LR 是舊管線內融合校準；桌面 ml 是另一套個人化雙路引擎。

---

## 資料流（現行）

```text
APP / CAI ──建圖欄位──┐
訊息正文 ────────────┼──► dual_agent/dai/fraud_dual（內嵌 ml 引擎）
                     │         │
                     │         ▼
                     │    Result_A + Result_B（可選）
                     │    (threat / context / scam_type)
                     │         │
                     ▼         ▼
              risk_analysis/dual_path.py（適配層）
                     │
                     ▼
              風險卡／CAI：並列雙分 + Narrator + verdict
```

介面契約對齊桌面：`AnalyzeRequest` / `ResultA`（見 `ml/src/shared/schemas.py` 與 `fraud_dual/shared/schemas.py`）。

桌面 `ml` 仍可獨立跑 `uvicorn src.api.app:app` + `POST /analyze` 做研究驗證；產品路徑不經 HTTP。

---

## 現況

| 項目 | 說明 |
|------|------|
| 桌面 `ml` | Path A（ML+GNN）+ Path B（Ollama）+ 規格總冊 `計劃書.md` |
| Dual-agent | `dual_path_analyze` → `fraud_dual` pipeline |
| 模型目錄 | `Dual-agent/data/fraud_dual_models/`（`threat_models.joblib`、`context_hetero.pt` 等） |
| 建圖來源 | `profile_store` + 推斷 relation／channel |
| 重訓流程 | 在 `ml` 訓練 → 複製模型至 `fraud_dual_models/` |

---

## 與舊 RISK_SCORING 的關係

[RISK_SCORING.md](./RISK_SCORING.md) 主章節已改寫為**雙路徑主路徑**；舊 7 步 DAG 與單一 `risk_score` 移入「legacy 附錄」。
