# ScamSentinel CAI Hybrid 重構計畫

> 最後更新：2026-09-02  
> 狀態：H1 已完成（259 pytest 全綠）；H2 反饋與 H3 Mobile UX 待開始  
> 遠端：https://github.com/jayterry/Dual-agent.git

本文件為 **唯一** Hybrid 架構計畫書；原先分散的 Prompt 初稿、欄位規劃、Context 分層等文件已併入此處，程式中的 prompt 正文見 `dual_agent/cai/hybrid/prompts/`。

---

## 一、產品定位

**ScamSentinel** 不是通用生活助理，而是 **訊息防詐 Agent**：

| 範圍內 | 範例 |
|--------|------|
| 送審 | 貼簡訊全文 → `call_dai` |
| 缺正文 | 「幫我看是不是詐騙」→ `ask_user` |
| 送審後追問 | 「有風險嗎」→ ReAct 讀 `task_snapshot` |
| 關係記憶 | 「我媽叫 Yuri」→ `profile_remember_relation` |
| 回想關係 | 「我媽媽叫什麼」→ Profile 查表短路 |
| 拒絕待審 | 「不用了」→ 禮貌結束 |

| 範圍外 | 處理 |
|--------|------|
| 天氣、搜尋、開網頁 | **已移除技能**；NLP 標 `out_of_scope` |
| 閒聊、猜謎、嗜好記憶 | 禮貌拒答並引導送審 |

---

## 二、架構總覽

### 五階段管線

```
本輪輸入 → NLP（MessageFeatures）→ Planner 初稿 → Execute → ReAct Replan → finish
                ↓ recall_relation
           Profile 查表短路（不進 Planner/ReAct LLM）
```

### 三台 LLM 分工

| 角色 | 模組 | 職責 |
|------|------|------|
| **NLP** | `hybrid/message_features.py` | 意圖 + 五組特徵 JSON |
| **Planner** | `planner_llm.py` | 依特徵排初稿 todos |
| **ReAct Replan** | `replan_llm.py` → `hybrid/react_replan.py` | 逐步 thought→action→observation |

**Memory LLM 已退役**（Hybrid 啟用時略過 `try_handle_memory_turn`）；關係讀寫改走 profile skills + NLP。

### 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `CAI_HYBRID_ENABLED` | `true` | 關閉則走舊 Planner/Memory 路徑 |
| `CAI_MESSAGE_FEATURES_MODEL` | 同 ingress 模型 | NLP 特徵抽取模型 |

---

## 三、MessageFeatures Schema

NLP 一次輸出五組欄位（Pydantic：`dual_agent/cai/hybrid/schemas.py`）：

### 1) `turn_intent`

| 欄位 | 說明 |
|------|------|
| `primary_goal` | `review_sms` \| `ask_missing_body` \| `follow_up_review` \| `remember_relation` \| `recall_relation` \| `out_of_scope` |
| `is_follow_up` | 是否接續上一輪送審 |
| `confidence` | 0–1 |
| `intent_rationale_zh` | 繁中 1–2 句理由 |

### 2) `content`

待審正文、使用者評論、通道、詐騙訊號標籤等。

### 3) `social`

關係類別（親戚/朋友）、稱謂、姓名、是否代他人詢問。

### 4) `gaps`

缺正文、需確認關係、超出產品範圍等缺口旗標。

### 5) `capabilities`

`required_types`、`domain_tags`、`suggested_skills`、`is_multi_step`。

---

## 四、技能白名單（MVP）

實作：`dual_agent/cai/hybrid/gates.py`

| `primary_goal` | 允許 skills |
|----------------|-------------|
| `review_sms` | `call_dai`, `ask_user`, `confirm` |
| `ask_missing_body` | `ask_user`, `confirm` |
| `follow_up_review` | `ask_user`, `confirm` |
| `remember_relation` | `profile_remember_relation`, `ask_user`, `confirm` |
| `recall_relation` | `profile_recall_relation`, `confirm` |
| `out_of_scope` | `confirm` |

**CAI 現存技能目錄**（`dual_agent/cai/skills/`）：

- `call_dai`, `ask_user`, `confirm`
- `profile_remember_relation`, `profile_forget_relation`, `profile_recall_relation`

**已移除**（超出 MVP）：`weather`, `search_web`, `fetch_url`, `instant_answer`, `open_app`, `open_url_readonly`

---

## 五、User Profile（五欄）

| UI 欄位 | API 鍵 | 用途 |
|---------|--------|------|
| 名稱 | `display_name` | 稱呼 |
| 年齡 | `age` → `age_band` | DAI 情境分 |
| 職位 | `job_title` → `occupation` | DAI 情境分 |
| 關係 | `relations` | 親戚/朋友 × 稱謂 × 姓名[] |
| 常用 APP | `primary_apps` | 管道先驗 |

**Context 分層**：Profile = L3 持久事實；MessageFeatures = L0 本輪；Context Pack = 組裝視圖。

### 關係記憶流程

- **recall**：NLP 產出 `recall_relation` + `relation_label` → `hybrid/recall.py` 查 Profile 模板回答（**不呼叫 LLM**）
- **remember**：NLP 產出 `remember_relation` → Planner 排 `profile_remember_relation` → FSM 確認 → 寫庫
- **forget**：`profile_forget_relation`

---

## 六、Prompt 落地

| 檔案 | 用途 |
|------|------|
| `hybrid/prompts/nlp_system.txt` | NLP system prompt |
| `hybrid/prompts/planner_system.txt` | Planner system prompt |
| `hybrid/prompts/react_replan_system.txt` | ReAct Replan system prompt |
| `hybrid/prompts/fewshots/message_features.json` | NLP few-shot（6 則） |
| `hybrid/prompts/__init__.py` | `load_prompt()` / `load_fewshots()` |

撰寫策略：**短 System、厚 User**；各 prompt 含【App 範圍】區塊與 JSON 樣本。

維護工具：`scripts/extract_hybrid_prompts.py`（自 Drafts 抽出，Drafts 已刪除）。

---

## 七、程式模組布局

```
dual_agent/cai/hybrid/
├── __init__.py
├── schemas.py           # MessageFeatures, ReActOutput
├── message_features.py  # invoke_message_features()
├── gates.py             # allowed_skills_for, filter_tool_catalog
├── recall.py            # try_recall_relation_shortcut()
├── validate.py          # validate_planner_from_features()
└── prompts/             # 三份 system + fewshots

dual_agent/cai/
├── plan_execute.py      # Hybrid 編排主入口
├── planner_llm.py       # _invoke_planner_hybrid()
├── replan_llm.py        # Hybrid 時委派 react_replan；否則 legacy Replan
├── planner_validate.py  # legacy 路徑仍用（漸進移除）
└── skills/              # MVP 白名單技能
```

### 編排順序（`plan_execute.run_plan_and_execute`）

1. Ingress / Context Pack
2. **Hybrid ON**：`invoke_message_features` → recall 短路 → out_of_scope 短路
3. Memory LLM 短路（Hybrid OFF 時）
4. Planner（Hybrid 時讀 MessageFeatures + 過濾 catalog）
5. `validate_planner_from_features` 或 legacy `validate_planner_output`
6. Execute + Replan 迴圈

---

## 八、實作階段與進度

### Phase H0 — 拔除護欄與收斂範圍

| 項目 | 狀態 |
|------|------|
| 刪除 `semantic_router.py` | ✅ |
| 刪除 `follow_up_direct.py` | ✅ |
| 移除 out-of-scope skills（6 個目錄） | ✅ |
| 移除相關 tests / scripts | ✅ |
| `plan_execute` 移除 semantic_router / follow_up 依賴 | ✅ |
| Hybrid 時略過 Memory LLM | ✅ |
| 刪除 `planner_validate.py` | ⏳ 漸進（legacy 路徑仍用） |
| 刪除 `review_entry_eligibility` regex | ⏳ 高耦合，H0 後段 |
| 刪除 `ingress.py` regex 鏈 | ⏳ 高耦合，H0 後段 |

### Phase H1 — 五階段 + ReAct

| 項目 | 狀態 |
|------|------|
| `MessageFeatures` schema + NLP | ✅ |
| profile_* skills（3 個） | ✅ |
| Planner Hybrid prompt + validate | ✅ |
| `plan_execute` 接入 Hybrid | ✅ |
| `react_replan.py` + ReAct 單步 action | ✅ |
| `replan_llm.py` 改 ReAct（廢 `updated_todos`） | ✅ 已接入（Hybrid 時走 `react_replan.py`） |
| `result_fusion.py` | ⏳（H2 前可選） |
| pytest 全綠 | ✅ 259 passed, 1 skipped |

### Phase H2 — 全局反饋

| 項目 | 狀態 |
|------|------|
| `feedback.py` + TurnTrace | ⏳ |
| `problem_report_runner` 新增 `message_features` scenario | ⏳ |
| 重寫 `agent_full_coverage` 對齊五階段 | ⏳ |

### Phase H3 — Mobile UX

| 項目 | 狀態 |
|------|------|
| `thinking.entries` 面板 | ⏳ |
| `GET /pipeline` 回傳 thinking | ⏳ |
| smsagent `ThinkingProcessPanel` | ⏳ |

### Track B — ML（平行）

DAI `dual_path_analyze` 不變；詐騙 ML 在獨立 `ml` repo。

---

## 九、已刪除模組清單

| 模組 / 檔案 | 取代方式 |
|-------------|----------|
| `semantic_router.py` | NLP `MessageFeatures` + Planner |
| `follow_up_direct.py` | ReAct 讀 snapshot；recall 查表 |
| `weather/`, `search_web/`, … | 移除；`out_of_scope` |
| `tests/test_semantic_router.py` 等 | 刪除或改 Hybrid 測試 |
| `scripts/run_semantic_router_batch.py` | 刪除 |
| 分散 Hybrid 設計 doc（7 份） | 併入本文件 |

**仍保留（過渡）**：`planner_validate.py`、`review_entry_eligibility.py`、`ingress_router/`、`memory_direct.py`（非 Hybrid 路徑）。

---

## 十、驗收標準

1. 架構以 **NLP → Planner → Execute → ReAct** 描述；無 orphan 護欄模組。
2. MVP 技能僅防詐 + 關係記憶；catalog 不含 weather/search。
3. 「我媽媽叫什麼」→ Profile 查表正確回答。
4. 送審、缺正文、追問、記住關係 Demo 可跑通。
5. Mobile Demo 僅防詐場景腳本。

---

## 十一、與其他文件的關係

| 文件 | 關係 |
|------|------|
| [專案進度與目標.md](./專案進度與目標.md) | 產品總覽；CAI 架構以本文件為準 |
| [RISK_SCORING.md](./RISK_SCORING.md) | DAI 雙路徑評分（不變） |
| [SKILLS_MATRIX.md](./SKILLS_MATRIX.md) | 需重跑 `generate_skills_matrix.py` 更新 |
| [VERIFICATION_WORKFLOW.md](./VERIFICATION_WORKFLOW.md) | 測試流程；semantic_router scenario 已廢止 |
