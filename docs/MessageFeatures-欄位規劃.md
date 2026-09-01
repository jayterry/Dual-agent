# MessageFeatures 欄位規劃

> 狀態：設計定案（待實作）  
> 最後更新：2026-09-01  
> 對應模組（規劃）：`dual_agent/cai/hybrid/message_features.py`、`dual_agent/cai/hybrid/schemas.py`  
> 相關文件：[UserProfile-欄位規劃.md](./UserProfile-欄位規劃.md)（L3 持久 Context）、[Context-分層.md](./Context-分層.md)

## 定位

Hybrid 管線第一階：**NLP 從「本輪輸入」抽出結構化特徵**，產出 `MessageFeatures` JSON，再交給 **Planner 排任務**。

```
本輪輸入 → NLP（MessageFeatures）→ Planner 排任務 → ReAct 執行
```

### NLP 負責

- 切／抽本次訊息的**結構化特徵**（四組欄位）
- 分離 `artifact_text`（待審正文）與 `user_comment`（使用者意圖／背景）
- 標註關係、缺口、詐騙訊號標籤
- 標註本輪**所需能力類型**（工具调用、长期记忆、多步推理等）

### NLP 不負責

- 直接排任務（`call_dai`、`ask_user` 等由 Planner 決定）
- 細粒度 `segments[]` 切段
- 單一 `brief_for_planner` 一段話摘要
- 用 regex 規則表補救分類

### 短路路由（不進 ReAct LLM）

| `primary_goal` | 後段處理（確定性） |
|----------------|-------------------|
| `recall_relation` | **查 Profile** `relations[category][label]` → 模板回答；**不** call ReAct LLM |
| `remember_relation` | **寫 Profile**（確認 FSM + skill handler）；ReAct 可選，通常 0～1 步 |

仍進 ReAct：`review_sms`、`follow_up_review`、`out_of_scope` 等。

---

## 結構總覽

五組、共 **22 個欄位**，NLP 一次輸出 JSON。

| 組別 | 用途 |
|------|------|
| `turn_intent` | 本輪主要意圖 |
| `content` | 訊息內容與待審正文 |
| `social` | 人際關係與代問 |
| `gaps` | 任務缺口（Planner 排程依據） |
| `capabilities` | 所需能力類型（Planner／ReAct 路由依據） |

---

## 1. `turn_intent` — 本輪意圖

| 欄位 | 型別 | 說明 |
|------|------|------|
| `primary_goal` | enum | 見下方枚舉 |
| `is_follow_up` | bool | 是否接續上一輪送審 |
| `confidence` | float | NLP 自評信心，0–1 |

### `primary_goal` 枚舉

| 值 | 說明 |
|----|------|
| `review_sms` | 送審簡訊／可疑內容 |
| `ask_missing_body` | 使用者想審但尚未提供正文（或僅表達意圖） |
| `follow_up_review` | 送審完成後的追問（解讀結果、追問細節） |
| `remember_relation` | 記住關係（如「我媽叫王美玲」）→ Memory 短路 |
| `recall_relation` | 回想關係（如「我兒子是誰」）→ Memory 短路 |
| `out_of_scope` | 超出產品範圍（閒聊、猜謎、天氣等） |

---

## 2. `content` — 訊息內容特徵

| 欄位 | 型別 | 說明 |
|------|------|------|
| `has_reviewable_body` | bool | 是否有可送 DAI 的正文 |
| `artifact_text` | string? | 抽出之待審正文（不含「幫我看」等包裝句） |
| `user_comment` | string? | 使用者自己的話（意圖／背景） |
| `body_source` | enum | 正文來源，見下方 |
| `contains_url` | bool | 是否含 URL |
| `contains_phone` | bool | 是否含電話 |
| `contains_financial_terms` | bool | 是否含金融相關詞 |
| `scam_signal_tags` | string[] | NLP 標的詐騙訊號（非規則表） |
| `text_length` | int | 原始輸入字元數 |

### `body_source` 枚舉

| 值 | 說明 |
|----|------|
| `inline` | 使用者直接在對話中貼正文 |
| `api_split` | 由 API／Ingress 預先拆分 |
| `sms_share` | 來自行動端簡訊分享 |

### `scam_signal_tags` 範例

NLP 自由標註，常見例如：

- `urgency` — 催促、限時
- `otp_request` — 要求驗證碼／OTP
- `bank_impersonation` — 冒充銀行／金融機構
- `link_phishing` — 可疑連結導向
- `prize_scam` — 中獎／獎品

（非固定枚舉；迭代時可收斂常用 tag 清單。）

---

## 3. `social` — 關係／代問

對齊 User Profile 五欄中之「關係」欄（`relations`：`親戚` / `朋友` → 稱謂 → 姓名[]）。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `mentions_relation` | bool | 是否提到人際關係 |
| `relation_category` | enum? | `親戚` \| `朋友` |
| `relation_label` | string? | 如 `媽媽`、`兒子`、`同事` |
| `relation_name` | string? | 本句提及的**姓名**（記住時由 NLP 抽出，如「叫 Yuri」→ `Yuri`） |
| `on_behalf_of_other` | bool | 是否代他人詢問（如「幫我媽看這則」） |

**NLP 階段即可判斷「媽媽是誰」類問題**：

| 使用者句 | NLP 產出 |
|----------|----------|
| 「我媽媽是誰 / 叫什麼」 | `primary_goal=recall_relation`，`relation_label=媽媽` |
| 「我媽叫 Yuri」 | `primary_goal=remember_relation`，`relation_label=媽媽`，`relation_name=Yuri` |
| 「幫我媽看這則…」 | `primary_goal=review_sms`，`relation_label=媽媽`，`on_behalf_of_other=true`（**不是** recall） |

後段只需 **查 Profile 或寫 Profile**，不必再用 LLM「猜」意圖。

---

## 4. `gaps` — 任務缺口

供 Planner 判斷本輪是否缺資訊、是否超出範圍。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `missing_body_for_review` | bool | 想審但無正文 |
| `needs_profile_relation_confirm` | bool | 提到關係但 Profile 無對應姓名 |
| `out_of_product_scope` | bool | 閒聊、非防詐產品能力等 |

---

## 5. `capabilities` — 所需能力類型

NLP 標註本輪完成任務需要哪些**執行能力**與**領域標籤**，供 Planner 選路由（Memory 短路 / ReAct / 單步 finish）。

| 欄位 | 型別 | 說明 |
|------|------|------|
| `required_types` | string[] | 執行能力枚舉（可多選），見下方 |
| `domain_tags` | string[] | 領域能力枚舉（可多選），見下方 |
| `suggested_skills` | string[] | MVP 技能白名單建議：`call_dai`、`ask_user` |
| `is_multi_step` | bool | 是否預期需 ReAct 多步（`multi_step_reasoning` 的快捷旗標） |

### `required_types` 枚舉（執行機制）

| 值 | 中文 | 說明 | 典型路由 |
|----|------|------|----------|
| `tool_call` | 需工具调用 | 需呼叫 skill（`call_dai`、`ask_user`） | ReAct → Executor |
| `long_term_memory` | 需长期记忆 | 需讀寫 Profile `relations` 或 `task_snapshot` | Memory 短路或 ReAct 讀 snapshot |
| `multi_step_reasoning` | 需多步推理 | 需 ReAct 多輪 thought→action | ReAct 迴圈 |
| `user_interaction` | 需用户交互 | 需向使用者追問或確認 | `ask_user` |
| `direct_response` | 可直接回应 | 禮貌拒答或簡答，无需工具 | ReAct `finish` / decline |

### `domain_tags` 枚舉（產品領域 — ScamSentinel MVP）

| 值 | 說明 | 常搭配 `required_types` |
|----|------|-------------------------|
| `safety_review` | 防詐送審 | `tool_call` |
| `ask_missing_artifact` | 缺正文追問 | `user_interaction` |
| `follow_up_review` | 送審後追問 | `long_term_memory`, `multi_step_reasoning` |
| `relation_memory` | 記住／回想關係人 | `long_term_memory` |
| `fraud_education` | 防詐科普簡答 | `direct_response` 或 `multi_step_reasoning` |
| `out_of_scope` | 超出產品範圍 | `direct_response` |

### `primary_goal` → 典型能力對照

| `primary_goal` | 典型 `required_types` | 典型 `domain_tags` |
|----------------|----------------------|---------------------|
| `review_sms` | `tool_call` | `safety_review` |
| `ask_missing_body` | `user_interaction` | `ask_missing_artifact` |
| `follow_up_review` | `long_term_memory`, `multi_step_reasoning` | `follow_up_review` |
| `remember_relation` / `recall_relation` | `long_term_memory` | `relation_memory` |
| `out_of_scope` | `direct_response` | `out_of_scope` |

### `primary_goal` → 後段路由（定案）

| `primary_goal` | NLP 已抽出 | 後段（尽量不用 LLM） |
|----------------|------------|---------------------|
| `recall_relation` | `relation_label`（+ `relation_category`） | **Profile 查表** → 模板句 |
| `remember_relation` | `relation_label` + `relation_name` | **确认 FSM** → 写 Profile |
| `review_sms` | `artifact_text` 等 | ReAct → `call_dai` |

> NLP **同時輸出** `turn_intent.primary_goal` 與 `capabilities`：前者語意意圖，後者執行代價；Planner 以兩者一致為佳，不一致時以 `capabilities` + `gaps` 輔助判斷。

---

## JSON 骨架

```json
{
  "turn_intent": {
    "primary_goal": "review_sms",
    "is_follow_up": false,
    "confidence": 0.0
  },
  "content": {
    "has_reviewable_body": false,
    "artifact_text": null,
    "user_comment": null,
    "body_source": "inline",
    "contains_url": false,
    "contains_phone": false,
    "contains_financial_terms": false,
    "scam_signal_tags": [],
    "text_length": 0
  },
  "social": {
    "mentions_relation": false,
    "relation_category": null,
    "relation_label": null,
    "relation_name": null,
    "on_behalf_of_other": false
  },
  "gaps": {
    "missing_body_for_review": false,
    "needs_profile_relation_confirm": false,
    "out_of_product_scope": false
  },
  "capabilities": {
    "required_types": [],
    "domain_tags": [],
    "suggested_skills": [],
    "is_multi_step": false
  }
}
```

---

## 範例：代媽媽送審

**輸入**：「我媽收到這則，幫我看是不是詐騙：【台新銀行】您的帳戶異常，請立即點擊連結驗證…」

```json
{
  "turn_intent": {
    "primary_goal": "review_sms",
    "is_follow_up": false,
    "confidence": 0.92
  },
  "content": {
    "has_reviewable_body": true,
    "artifact_text": "【台新銀行】您的帳戶異常，請立即點擊連結驗證…",
    "user_comment": "我媽收到這則，幫我看是不是詐騙",
    "body_source": "inline",
    "contains_url": true,
    "contains_phone": false,
    "contains_financial_terms": true,
    "scam_signal_tags": ["urgency", "bank_impersonation", "link_phishing"],
    "text_length": 68
  },
  "social": {
    "mentions_relation": true,
    "relation_category": "親戚",
    "relation_label": "媽媽",
    "on_behalf_of_other": true
  },
  "gaps": {
    "missing_body_for_review": false,
    "needs_profile_relation_confirm": false,
    "out_of_product_scope": false
  },
  "capabilities": {
    "required_types": ["tool_call"],
    "domain_tags": ["safety_review"],
    "suggested_skills": ["call_dai"],
    "is_multi_step": false
  }
}
```

**Planner 預期**：`call_dai(artifact=artifact_text)`

---

## Planner 讀特徵排任務（參考規則）

Planner 主輸入 = Context Pack + **MessageFeatures JSON**（不以 raw 全文為主鍵）。

| 特徵條件 | 預期任務 |
|----------|----------|
| `capabilities.domain_tags` 含 `safety_review` 且 `has_reviewable_body` | `call_dai(artifact=artifact_text)` |
| `capabilities.domain_tags` 含 `ask_missing_artifact` 或 `missing_body_for_review` | `ask_user`（請貼正文） |
| `capabilities.required_types` 含 `long_term_memory` + `follow_up_review` | ReAct `finish`（讀 task snapshot） |
| `capabilities.domain_tags` 含 `relation_memory` | 不進 Planner → Memory |
| `capabilities.domain_tags` 含 `out_of_scope` | `decline` / 引導送審 |

特徵抽錯時，優先迭代 **NLP few-shot**，不加 regex 護欄。

---

## 與其他設計的關係

| 項目 | 說明 |
|------|------|
| User Profile | L3 持久 Context，見 [UserProfile-欄位規劃.md](./UserProfile-欄位規劃.md)、[Context-分層.md](./Context-分層.md) |
| 技能白名單 MVP | `call_dai`、`ask_user` |
| 反饋與優化 | 見 [Hybrid-反饋與優化.md](./Hybrid-反饋與優化.md)（TurnTrace、mismatch → 改 prompt） |
| 思考過程展示 | 見 [Hybrid-思考過程展示.md](./Hybrid-思考過程展示.md) |
| System Prompt | 見 [Hybrid-System-Prompts.md](./Hybrid-System-Prompts.md) |
| 拔除模組（H0） | `planner_validate` 規則校正、`semantic_router`、`follow_up_direct`、Ingress regex 鏈等 |
| 實作順序 | H1：schemas + message_features + ReAct prompts |

---

## 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-01 | 初版：四組 18 欄位定案；NLP 抽特徵 → Planner 排任務 |
| 2026-09-01 | 新增 `social.relation_name`；recall/remember 在 NLP 阶段判定，后段 Profile 查表/写入 |
