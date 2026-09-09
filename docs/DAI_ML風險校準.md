# DAI 風險評分 ML 校準

> 最後更新：2026-08-12  
> 狀態：**規劃中**（雙路線並行：Route B LLM 語意路線 + Route C ML 校準；尚無大量標註，ML Phase 1 待 Bootstrap）  
> 相關文件：[RISK_SCORING.md](./RISK_SCORING.md)、[語意分析改善計畫.md](./語意分析改善計畫.md)（§1.1、§4.4）

---

## 〇、雙路線定案（與語意分析改善計畫對齊）

**維持雙路線，不互相取代。** 共用規則底線與機器層（rules、TI、TLS、toxic）；融合層依模式切換。

| 路線 | `DAI_RISK_FUSION_MODE` | 核心做法 | 本文件章節 |
|------|------------------------|----------|------------|
| **Legacy** | `legacy`（預設） | 人工權重 + `semantic_llm` H/I | 二、現況 |
| **B. LLM 語意** | `enhanced_embed`（規劃） | **KEA + TAPE → 文本增強 → 深度句嵌入** | **〇.1** |
| **C. ML 校準** | `ml_lr` / `ml_rf` | 特徵向量 + LR／RF → `p_fraud` | 三～七 |

```
簡訊/通知正文 + 機器層分項
        │
        ▼
   規則底線（Tier 90、hard guard）─── 兩路皆不可繞過
        │
        ├─► Route B：kea_tape_llm ──► enhanced_text ──► embed ──► r_embed + 規則融合
        │
        └─► Route C：KEA/TAPE/機器/嵌入特徵 ──► feature_extractor ──► LR/RF ──► p_fraud
```

**LLM 路線交付標準**：必須實作 KEA（實體、意圖假設、關鍵片語）與 TAPE（模式、人話解釋），並對**增強後文本**做嵌入比對；**不以僅輸出 H/I labels 為長期終點**（`semantic_llm` 為過渡）。詳見 [語意分析改善計畫 §4.4](./語意分析改善計畫.md)。

### 〇.1 Route B：KEA / TAPE + 文本增強嵌入（LLM 主交付）

| 步驟 | 說明 |
|------|------|
| 1. KEA | 背景 LLM：抽取實體（URL、電話…）、意圖假設（如假冒親友）、`keyphrases`；`text` 須為原文子字串 |
| 2. TAPE | 同次 JSON：`patterns[]`、`tape_summary`（風險卡用）；**不**輸出最終 `risk_score` |
| 3. 文本增強 | `enhanced_text = 原文 + 【KEA】+ 【TAPE】` 固定模板 |
| 4. 深度句嵌入 | `embed(enhanced_text)`；與詐騙／正常話術原型庫 cosine（Chroma，類 `toxic_chroma`） |
| 5. 融合 | `r_embed_enhanced` + 機器層 + 規則護欄 → `risk_score` |

環境變數（規劃）：`DAI_TEXT_ENHANCE=1`、`DAI_RISK_FUSION_MODE=enhanced_embed`。實作掛點見語意分析改善計畫 **P3b**、`kea_tape_llm.py`。

Route B 與 Route C **可並行 shadow**；標註充足後，Route C 的 `feature_extractor` 應**優先吃** Route B 的結構化輸出與嵌入特徵，而非僅 one-hot 規則。

**與 CAI 對齊**：Route B 的 KEA/TAPE/增強嵌入與 CAI Ingress、`semantic_router` 共用語意能力層（見 [語意分析改善計畫 §1.2](./語意分析改善計畫.md)）；DAI 解讀**待審正文威脅**，CAI 解讀**使用者任務意圖**，底層同一套標準。

---

## 一、專案目標

改良 DAI 風險評分系統：目前對簡訊、通知、連結等內容計算 **0–100 risk score**，輸出 `allow` / `warn` / `block`。現有融合公式中的權重（如機器層 65%、語意層 35%、支援加成 0.15/0.10）多為**工程先驗值**，尚未經大量標註資料校準，可信度與準確性有優化空間。

**參考案例**：Stripe Radar（交易詐欺風險評分）。我們**不完全複製**，而是借鑑其 **「規則底線 + 特徵工程 + ML 校準」** 概念，並因應**文字訊息**場景融入 LLM。

### 三層架構（規則 + 雙路融合）

| 層級 | 職責 |
|------|------|
| **Rule Engine** | 安全底線；高風險規則硬擋，**兩路皆不得洗低** |
| **Route B：LLM 語意** | KEA + TAPE + 增強文本嵌入 → `r_embed`／結構化特徵 |
| **Route C：ML** | 特徵向量 + LR/RF 校準 → `p_fraud`（可含 Route B 產出特徵） |

```
簡訊/通知/URL 正文
    │
    ├─► Rule Engine ────────────────┐
    ├─► Route B：KEA/TAPE + embed ──┼─► 融合（mode 分支）──► risk_score + verdict
    ├─► Route C：Feature Vector ──► ML ─┘
    │
    └─► hard guard（規則覆寫灰色地帶）
```

**差異（相對初版）**：LLM 不再僅「標籤 → ML 特徵」；**Route B 可獨立融合上線**；Route C 待標註後與 Route B shadow 對照。

### 與 Stripe Radar 對照

| Stripe Radar | DAI（本專案） |
|--------------|---------------|
| 交易特徵（金額、IP、裝置） | 簡訊/通知文字、URL、來源、規則命中 |
| 規則硬擋高風險交易 | `rules.py` Tier 90 + `hard >= 85` 護欄 |
| ML 估計詐欺機率 | Logistic Regression → Random Forest |
| 風險分數 | `P(fraud)` 映射 0–100 + `allow`/`warn`/`block` |

**差異**：我們處理**非結構化中文訊息**；LLM 負責語意與標籤，傳統 ML 負責校準與組合判斷。

---

## 二、現況（改造起點）

### 已實作

| 項目 | 位置 |
|------|------|
| 7 步審查 DAG | `dual_agent/dai/skills/_pipeline_steps.py` |
| 硬規則 `r_rules` | `dual_agent/dai/risk_analysis/rules.py` |
| URL 情資 / TLS / 毒樣 | `providers.py`、`toxic_score.py` |
| 語意層 H/I + labels | `semantic_llm.py` |
| 融合 v2（人工權重） | `verdict.py` → `fuse_risk_score_weighted()` |
| UEBA 調整 | `user_db.py` |
| 公式說明 | `docs/RISK_SCORING.md` |

### 現行融合（legacy）摘要

```
r_machine_final = max(四項) + 0.15×次高 + 0.10×第三高
r_fused         = 0.65 × r_machine_final + 0.35 × r_llm_100
risk_score      = max(r_fused + UEBA, semantic_floor(labels))
```

環境變數：`DAI_R_LLM_WEIGHT`（預設 0.35）。

### 缺口

- 尚無標註訓練資料
- 無 `scikit-learn`、無離線訓練腳本
- LLM `labels` 主要用於 `semantic_floor`，未系統化為 ML 特徵
- 融合係數與標籤下限表為人工設定

---

## 三、兩階段 ML 路線

### Phase 1：Logistic Regression

**目標**：讓 risk score 不再只依賴人工權重，而是依標註資料學習各風險分項重要程度。

- 輸入：特徵向量（規則 one-hot、component_scores、LLM 標籤、結構特徵、UEBA）
- 輸出：`P(fraud)` → 0–100 分
- 可解釋：`coefficients.json` 檢視各特徵權重

### Phase 2：Random Forest

**目標**：資料量足夠後學習**非線性組合**（多個中等風險訊號同時出現 → 高風險）。

- 觸發建議：≥ **2000** 筆標註，且 LR validation AUC 趨於平穩
- 產出：`feature_importances.json`；Shadow mode 與 LR 對照後切換

---

## 四、Phase 0：標註資料集 Bootstrap

**現況**：尚無標註資料，需從頭建立。

### 4.1 標註 Schema

路徑：`data/risk_training/labels.jsonl`（範例：`labels.example.jsonl`）

```json
{
  "id": "uuid",
  "text": "簡訊正文…",
  "source": "sms",
  "label": "scam",
  "verdict_gt": "block",
  "fraud_types": ["phishing", "payment_pressure"],
  "annotator": "human",
  "split": "train"
}
```

| 欄位 | 說明 |
|------|------|
| `label` | `scam` \| `benign` \| `suspicious` |
| `verdict_gt` | 可選；對齊 `allow` / `warn` / `block` |
| `split` | `train` \| `val` \| `test` |

### 4.2 種子資料來源

| 來源 | 用途 |
|------|------|
| 既有毒樣 Chroma/JSON | 正樣本（scam） |
| 人工 benign 樣本 | 官方通知、正常物流、**工作指令句**（避免假陽性） |
| 公開台灣詐騙簡訊語料 | 擴充正樣本（若可取得） |
| Phase 1 最低量 | **≥ 300 scam + ≥ 300 benign**（建議 500/500） |

### 4.3 標註工具（規劃）

| 腳本 | 用途 |
|------|------|
| `scripts/import_risk_labels.py` | CSV/JSONL 匯入 |
| `scripts/annotate_risk_sample.py` | CLI 逐筆標註 |

---

## 五、特徵工程

新增模組：`dual_agent/dai/risk_analysis/ml/`

### `feature_extractor.py`

從 DAG 中間結果組**固定長度、可重現**特徵向量：

| 特徵群 | 內容 |
|--------|------|
| 規則 one-hot | `hit_otp`, `hit_loan_scam`, …（`rules.py` 全部 `rule_id`） |
| 連續分項 | `r_rules`, `r_threat_intel`, `r_tls`, `r_toxic_fused`, `tier_h`, `tier_i`, `r_llm_optional` |
| LLM 標籤 one-hot | `lbl_phishing`, `lbl_credential_harvesting`, … |
| 結構特徵 | `url_count`, `text_len`, `phone_count`, `amount_count` |
| UEBA | `delta_user`, `source_trusted`, `domain_unknown` |
| 來源 | `src_sms`, `src_notification`, … |

### 離線匯出

```bash
python scripts/export_risk_features.py \
  --labels data/risk_training/labels.jsonl \
  --out data/risk_training/features.parquet
```

對語料跑 DAG **至 `semantic_supplement` 止**（不跑舊融合），批次產出特徵矩陣。

---

## 六、Phase 1 實作細節

### 6.1 訓練

```bash
python scripts/train_risk_lr.py \
  --features data/risk_training/features.parquet \
  --out data/risk_models/lr_v1/
```

| 項目 | 說明 |
|------|------|
| 依賴 | `scikit-learn>=1.4`（待加入 `requirements.txt`） |
| 模型 | `LogisticRegression(class_weight='balanced')` |
| 可選 | `CalibratedClassifierCV`（Platt 校準） |
| 產出 | `model.pkl`、`metrics.json`、`coefficients.json` |

### 6.2 推論整合

掛點：`verdict.py` 新增 `fuse_risk_score_ml()`；`step_fuse_risk_and_ueba` 依模式分支。

| 環境變數 | 預設 | 說明 |
|----------|------|------|
| `DAI_RISK_FUSION_MODE` | `legacy` | `legacy` \| `enhanced_embed` \| `ml_lr` \| `ml_rf` |
| `DAI_ML_MODEL_PATH` | — | Route C：模型 `.pkl` 路徑 |
| `DAI_TEXT_ENHANCE` | `0` | Route B：啟用 KEA/TAPE 文本增強 |
| `DAI_EMBED_ENHANCED_TEXT` | `1` | Route B：對 `enhanced_text` 嵌入 |

報告擴充範例：

```json
"risk_fusion": {
  "mode": "ml_logistic_v1",
  "p_fraud": 0.62,
  "model_version": "lr_v1",
  "feature_snapshot": { }
}
```

### 6.3 LLM 角色（Route B：KEA / TAPE）

擴充／取代現有 `semantic_llm.py` 為 `kea_tape_llm.py`（或在其上升級）：

- **KEA**：`entities[]`、`keyphrases[]`、`intent_hypotheses[]`（如假冒親友、可疑連結）
- **TAPE**：`patterns[]`、`tape_summary`；供風險卡與 audit
- **文本增強**：拼接後 `embed(enhanced_text)`；話術原型 Chroma
- **禁止** LLM 直接輸出最終 `risk_score`
- `ml_*` 模式下：Route B 結構化欄位進 `feature_extractor`；停用或收斂 `semantic_floor`，避免雙重抬分
- `enhanced_embed` 模式：以 `r_embed_enhanced` + 規則融合為主；`semantic_llm` 純 H/I 逐步退役

詳細規格：[語意分析改善計畫 §4.4](./語意分析改善計畫.md)。

### 6.4 門檻

初期保留 `verdict_from_score` 的 **85 / 70** 門檻，僅替換分數來源；後續可在 validation set 上以 Fβ 或固定 FPR 重估。

---

## 七、Phase 2：Random Forest

| 項目 | 說明 |
|------|------|
| 腳本 | `scripts/train_risk_rf.py` |
| 模型 | `RandomForestClassifier`（限制 `max_depth`） |
| 能力 | 多訊號非線性組合（例：中等規則 + phishing 標籤 + 含 URL） |
| 上線 | Shadow mode 對照 LR → 切換 `DAI_RISK_FUSION_MODE=ml_rf` |

---

## 八、規則底線（始終保留）

對齊 Stripe「rules override」，以下**不受 ML 降權**：

1. `r_rules >= 90` 或 `r_threat_intel` 達最高檔 → `risk_score >= 85`，`verdict = block`
2. 可配置 `risk_rules_guard.yaml`：特定 `rule_id`（OTP、匯款威脅等）硬擋
3. ML 主導**灰色地帶**；明確惡意由規則兜底

---

## 九、評估與測試

| 測試 / 腳本 | 內容 |
|-------------|------|
| `test_feature_extractor.py` | 固定輸入 → 固定特徵 |
| `test_ml_risk_calibration.py` | 小資料集 LR 訓練與推論 |
| `test_rule_guard_overrides_ml.py` | Tier 90 時不得 `allow` |
| `scripts/eval_risk_model.py` | confusion matrix、calibration plot |
| 回歸 | `DAI_RISK_FUSION_MODE=legacy` 時 `test_risk_fusion_v2.py` 全過 |

---

## 十、實作順序（雙路線 PR）

```
PR1  標註 schema + feature_extractor + export_risk_features + 種子標註
PR2a Route B：kea_tape_llm + enhanced_text + scam_prototype_chroma + enhanced_embed 融合（語意分析 P3b）
PR2b Route C：train_risk_lr + eval（可消費 PR2a 特徵）
PR3   pipeline 整合（legacy / enhanced_embed / ml_lr 開關）+ shadow 對照 + 測試
PR4   （資料達標）train_risk_rf + 門檻校準 + RISK_SCORING 文件同步
```

**優先序**：Route B（KEA/TAPE+嵌入）與 PR1 種子標註可並行；Route C 訓練不依賴 Route B 上線，但特徵應對齊 Route B 輸出。

---

## 十一、待辦清單

| ID | 內容 | 路線 | 狀態 |
|----|------|------|------|
| dataset-schema | 標註 schema + 匯入工具 + 種子資料 | C | pending |
| feature-extractor | `ml/feature_extractor.py`（含 KEA/TAPE/embed 特徵） | C | pending |
| kea-tape-llm | `kea_tape_llm.py` + 文本增強 + `enhanced_embed` 融合 | **B** | pending |
| scam-prototype-chroma | 話術原型庫 + Chroma 比對 | **B** | pending |
| llm-feature-gen | KEA/TAPE 結構化輸出（取代僅 fraud_types） | B→C | pending |
| offline-replay | `export_risk_features.py` | C | pending |
| train-lr | `train_risk_lr.py` | C | pending |
| integrate-fusion-modes | `legacy` / `enhanced_embed` / `ml_lr` 管線整合 | B+C | pending |
| eval-harness | 測試 + 離線評估（含 embed raw vs enhanced ablation） | B+C | pending |
| train-rf | `train_risk_rf.py`（Phase 2） | C | pending |
| docs-ml | 更新 RISK_SCORING.md 融合章節 | — | pending |

---

## 十二、驗收標準

### Route B（`enhanced_embed`）

1. KEA 實體 `text` 原文子字串率 ≥ **95%**（回歸集）。
2. `embed(enhanced)` 對照 `embed(raw)`：詐騙召回 ↑ 或正常誤報 ↓（Phase 0 對照集）。
3. `tape_summary` 進風險卡；LLM **不**輸出最終 `risk_score`。
4. Tier 90 規則命中時，`verdict` 不得為 `allow`。

### Route C（`ml_lr` / `ml_rf`）

5. 種子資料 ≥ **600** 筆可完成 LR 訓練。
6. Validation **AUC > legacy**（同 val set）。
7. `ml_lr` 輸出含 `p_fraud` 與 `feature_snapshot`。

### 共通

8. `legacy` 模式與現行行為一致。
9. 三路模式可 shadow 對照，一鍵切換 `DAI_RISK_FUSION_MODE`。

---

## 十三、與其他主線的關係

| 主線 | 關係 |
|------|------|
| [語意分析改善計畫](./語意分析改善計畫.md) | **Route B 規格主文件**（§1.1、§4.4、P3b）；雙路線定案 |
| Ingress 複合動作誤排（Phase 0） | 建議先修；benign 種子需含工作指令句 |
| 公司知識圖譜 / 組織圖 | 正交，可並行 |
| 現行 RISK_SCORING.md | 上線後新增 `enhanced_embed`、`ml_logistic_v1` 章節 |

---

## 十四、相關程式路徑

| 路徑 | 說明 |
|------|------|
| `dual_agent/dai/risk_analysis/verdict.py` | 融合與判定（改造主檔） |
| `dual_agent/dai/skills/_pipeline_steps.py` | `step_fuse_risk_and_ueba` |
| `dual_agent/dai/risk_analysis/semantic_llm.py` | Legacy H/I（過渡） |
| `dual_agent/dai/risk_analysis/kea_tape_llm.py` | Route B：KEA/TAPE（規劃） |
| `dual_agent/dai/toxic_chroma.py` | 嵌入比對參考實作 |
| `data/scam_prototypes/` | 話術原型庫（規劃） |
| `docs/語意分析改善計畫.md` | Route B 完整規格 |
| `dual_agent/dai/risk_analysis/rules.py` | 規則引擎 |
| `docs/RISK_SCORING.md` | 現行公式完整說明 |
