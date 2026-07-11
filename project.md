# 專案背景與核心架構

你現在是一位資深 AI 軟體架構師與 Python 後端工程師。本專案是一個具備 RAG、回答、內容審核與學習紀錄功能的雙代理系統 Dual-Agent System，由 CAI 與 DAI 組成。

- CAI = Chat Agent Intelligence
  負責使用者互動、任務理解、Planner / Replan、Todo 編排、工具呼叫與最終回答。

- DAI = Defense Agent Intelligence
  負責安全審核、風險分析、RAG 安全檢索、資料入庫審查、資料正規化與結構化。

本系統的核心原則是：
CAI 是主控 Agent，但 CAI 不直接接觸底層資料庫；DAI 是 CAI 可呼叫的防守型 Tool / Agentic RAG。

請你協助我從零開始實作此系統，並嚴格遵守以下架構邊界與開發規範。

---

## 1. 核心架構邊界 Architecture Boundaries

### 1.1 CAI 不可直接碰資料庫

CAI 絕對不允許直接存取以下資料庫：

- Vector DB
- Quarantine DB
- Safe Knowledge DB
- Threat Memory DB
- Policy / Rule DB
- 任何底層資料庫或檔案型資料庫

CAI 若需要知識檢索、相似案例、威脅特徵、風險分析或入庫審核，必須透過 DAI Interface 呼叫 DAI。

### 1.2 DAI 是唯一 RAG 與安全審核入口

所有與以下功能相關的請求，都必須經過 DAI：

- RAG 檢索
- 安全檢索 Guarded Retrieval
- 內容風險分析 Risk Analysis
- 外部資料入庫前審查 Secure Ingestion
- 威脅特徵比對
- 安全規則查詢
- Quarantine 判斷

### 1.3 Raw Data 必須先經過 DAI

所有外部原始資料 Raw Data 進入記憶庫或資料庫前，必須經過 DAI 的 Ingestion Review：

- Normalize 正規化
- Sanitize 消毒 / 脫敏
- Structure 結構化
- Risk Score 風險評分
- Store Decision 入庫決策

未經 DAI 審查的 Raw Data 不得直接寫入任何 DB。

---

## 2. 系統流程設計

### 2.1 CAI 主流程

CAI 的主要流程如下：

User Prompt
→ CAI Memory / Context Layer
→ Context Pack
→ CAI Planner LLM
→ Todo List + TaskState
→ Todo 是否為空？

如果 Todo = []：
- 表示一般問答或不需要工具
- 交給 CAI Replan / Responder 直接產生 Final Answer
- 不進 Executor
- 不呼叫 DAI，除非回答需要安全知識或上下文佐證

如果 Todo ≠ []：
- 取 Todo[0]
- Executor 執行 Todo[0]
- 如果 Todo[0] 是 call_dai，則呼叫 DAI
- Executor 回傳 Result / Observation
- CAI Replan 根據 Result / Observation 決定：
  - Final Answer
  - New Todo
  - Modify Todo
  - Block Tool
  - Need User Input
  - Update TaskState

### 2.2 DAI 作為 CAI Tool

CAI 的工具清單中必須包含：

- call_dai

CAI 可以自行判斷何時呼叫 DAI。

DAI 呼叫輸入為：

- Context Pack
- User Prompt
- CAI Todo

DAI 回傳：

- Safety Report
- Evidence
- Risk Score
- Tool Restrictions
- Safe Context
- Recommended CAI Action

### 2.3 DAI 主要能力

DAI 需要支援三種任務：

1. Risk Analysis
   - 審核使用者提供的簡訊、通知、網址、網頁內容或工具結果
   - 回傳風險分數、風險標籤、原因、工具限制

2. Guarded Retrieval
   - 從 DAI Memory / RAG Layer 中檢索安全知識、威脅特徵、規則
   - 回傳 Safe Context 與 Evidence

3. Secure Ingestion
   - 對準備入庫的資料做正規化、消毒、結構化與風險評分
   - 決定 Store / Quarantine / Reject
   - 僅允許安全摘要或結構化特徵入庫，不可直接保存高風險 Raw Data

---

## 3. DAI Memory / RAG Layer

DAI 的記憶層是一個受控的安全 RAG 記憶庫。

初期請先設計邏輯分層，不必馬上接真實 Vector DB。

DAI Memory 包含：

1. Safe Knowledge DB
   - 可信防詐知識
   - 官方安全建議
   - 金融安全原則
   - 適合 Vector Search / RAG

2. Threat Memory DB
   - 詐騙特徵
   - 話術模式
   - 攻擊樣態
   - 威脅 indicators
   - 適合 Vector Search / RAG

3. Policy / Rule DB
   - 安全規則
   - blocked actions
   - trigger 條件
   - 適合結構化查詢，不應只依賴向量相似度

4. Quarantine DB
   - 高風險、待審核或不可直接引用的資料
   - 不可直接提供給 CAI 作為可信知識
   - 僅供 DAI 內部審核與追蹤使用

---

## 4. 記憶層與 Context Layer

CAI 需要自己的 Memory / Context Layer，但它不能直接碰 DAI DB。

CAI Memory / Context Layer 負責：

- 保存最近 10 輪互動作為 Recent Context Buffer
- 超過 10 輪後壓縮成 Rolling Summary
- 保存 TaskState
- 保存最近 Result / Observation 摘要
- 保存 pending_task / waiting_input 狀態
- 在每次呼叫 Planner 或 Replan 前，透過 Context Packer 產生 Context Pack

CAI 的 Context Pack 可以包含：

- user_prompt
- recent_context_summary
- rolling_summary
- task_state
- last_result_summary
- pending_task
- current_todo_list

但是不可以包含未消毒的高風險 Raw Data。

---

## 5. 狀態機與防呆機制

### 5.1 TaskState

所有任務必須有明確 TaskState。

TaskState 至少包含：

- new
- running
- waiting_input
- completed
- blocked
- failed

每次 Planner / Replan 都必須讀取並更新 TaskState。

### 5.2 Max Iterations

CAI 的 Replan loop 必須有 Max_Iterations 限制。

例如：

- MAX_REPLAN_ITERATIONS=5

一旦達到上限，必須停止循環並回傳 fallback message。

不得出現無窮 Replan。

### 5.3 Need User Input

如果 Replan 判斷資料不足，需要詢問使用者，必須：

- 設定 task_state = waiting_input
- 設定 pending_task / waiting_for
- 回傳 ask_user
- 下一輪使用者輸入必須被視為接續任務，而不是新任務

---

## 6. 型別與資料模型要求

請使用 Python + Pydantic 定義所有跨模組溝通合約。

至少需要定義以下模型：

- Todo
- TodoList
- TaskState
- MemoryContext
- ContextPack
- CAIPlannerOutput
- CAIReplanOutput
- ToolResult
- DAIRequest
- DAIResult
- IngestionReviewResult
- RetrievalResult
- RiskAnalysisResult
- StoreDecision

所有模型都要放在獨立的 models 模組中。

---

## 7. 編碼規範

### 7.1 強型別優先

所有重要資料傳遞都必須使用 Pydantic Models，不要用鬆散 dict 到處傳。

### 7.2 職責單一 SRP

每個函式或類別只做一件事情。

不要把以下邏輯塞在同一個巨大函式中：

- Prompt 組裝
- LLM 呼叫
- JSON 解析
- Tool 執行
- DB 寫入
- 狀態更新

### 7.3 模組化開發

請採用由內而外 Inside-Out 的開發順序：

1. 定義資料模型 models
2. 定義設定 config
3. 定義 logging
4. 定義 DAI Interface
5. 定義 DAI memory abstraction
6. 定義 DAI risk / retrieval / ingestion service
7. 定義 CAI planner / replan contracts
8. 定義 Executor
9. 定義 CAI main loop
10. 加入測試

---

## 8. 環境變數與部署準備

所有設定必須透過 .env 或環境變數管理，不得寫死。

至少包含：

- OPENAI_API_KEY or LLM_API_KEY
- VECTOR_DB_URL
- DATABASE_URL
- MAX_REPLAN_ITERATIONS
- LOG_LEVEL
- ENV

請提供 .env.example。

---

## 9. 結構化日誌 Observability

必須加入 Structured Logging。

在以下事件必須記錄 log：

- CAI Planner start / end
- CAI Replan start / end
- Executor 執行 Todo
- call_dai 開始與結束
- DAI risk analysis
- DAI guarded retrieval
- DAI secure ingestion
- DB store decision
- error / exception
- max iteration reached

Log 至少包含：

- event
- agent
- task_id
- todo_id
- status
- risk_score if available
- error if any

---

## 10. 測試要求

每完成一個模組，必須同時提供單元測試。

初期至少需要以下測試：

1. CAI 不得直接存取 DAI DB
2. CAI 必須透過 call_dai 取得 RAG / risk analysis
3. TaskState 可以從 running 轉 waiting_input / completed / blocked
4. Replan loop 達到 max iterations 會停止
5. DAI secure_ingestion 會將高風險資料導向 quarantine 或 threat_memory
6. DAI guarded_retrieval 會回傳 safe_context
7. Policy / Rule DB 不依賴 Vector Search
8. 未經 DAI 審核的 Raw Data 不得入庫

---

## 11. 開發互動原則

請不要一次生成整個大型專案。

請你先檢查目前資料夾結構，如果是空專案，請從以下順序開始：

第一步只做：
- 專案目錄規劃
- Pydantic models
- config
- structured logger
- 對應 unit tests

在開始寫程式碼之前，如果你對架構或命名有任何不清楚的地方，請先列出問題詢問我。

每次完成一個功能或模組後，請提供：
- 修改了哪些檔案
- 為什麼這樣設計
- 如何執行測試
- 下一步建議