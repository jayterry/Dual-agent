# Hybrid 思考過程展示

> 狀態：設計定案（待實作 H3）  
> 最後更新：2026-09-01  
> 原則：**保留現有流程圖**，**追加**可讀的思考過程面板  
> 相關：[MOBILE.md](../MOBILE.md)、[MessageFeatures-欄位規劃.md](./MessageFeatures-欄位規劃.md)

## 產品目標

使用者在等待回覆時，除了看到「現在跑到哪個節點」，還能看到 **Agent 在想什麼、為什麼這樣排**（繁中摘要，非 raw prompt）。

| 保留 | 新增 |
|------|------|
| `GET /pipeline` 的 `nodes[]` 流程圖 | `thinking.entries[]` 思考條目 |
| `steps[]` 粗步驟 fallback | 可折疊「思考過程」面板 |
| `headline_zh` 目前節點 | 完成後仍可展開本輪思考（可選） |

**不取代**流程圖；兩者並列：**上 = 流程在哪一步，下 = 這一步想了什麼**。

---

## UI 佈局（手機 App）

```
┌─────────────────────────────┐
│  LinearProgressIndicator    │
├─────────────────────────────┤
│  【現有】PipelineFlowchart   │  ← nodes + headline_zh（不變）
│  ○ 載入上下文 → ● Planner … │
├─────────────────────────────┤
│  ▼ 思考過程（3）             │  ← 新增，預設展開；可折疊
│  · 理解：這是要送審的簡訊…   │
│  · 規劃：已有正文，呼叫 DAI   │
│  · 觀察：風險分 78，準備說明 │
└─────────────────────────────┘
```

桌面端（Tk/Qt）：可選 Phase H3+ 同步；MVP 以 Mobile 為主。

---

## API 設計（向後相容）

在現有 `get_pipeline_status()` 回傳中 **追加** 可選欄位；舊版 App 忽略即可。

### 新增頂層欄位

| 欄位 | 型別 | 說明 |
|------|------|------|
| `thinking` | object? | 本輪思考過程；無則省略 |
| `thinking.entries` | array | 按時間排序 |
| `thinking.collapsed_default` | bool | App 是否預設折疊（預設 `false`） |

### `thinking.entries[]` 每項

| 欄位 | 型別 | 說明 |
|------|------|------|
| `id` | string | 如 `tf-001` |
| `phase` | enum | 見下方 |
| `node_id` | string? | 對應流程圖節點 id（如 `planner_llm`） |
| `label_zh` | string | 短標題，如「理解訊息」 |
| `summary_zh` | string | **使用者可讀**繁中摘要（1–3 句） |
| `thought_zh` | string? | ReAct thought（消毒後） |
| `action` | object? | `{ "type": "tool"\|"finish"\|"ask_user", "skill": "...", "brief_zh": "..." }` |
| `observation_zh` | string? | 工具執行結果摘要 |
| `status` | enum | `pending` \| `active` \| `done` |
| `ts` | string | ISO8601 |

### `phase` 枚舉（對齊 Hybrid 五階段）

| 值 | 對應節點 | 內容來源 |
|----|----------|----------|
| `message_features` | `ingress` / 新 `nlp_features` | MessageFeatures 人話摘要 |
| `memory` | `memory_llm` | Memory 決策摘要 |
| `plan` | `planner_llm` | Planner 排任務理由 |
| `react` | `replan_llm` | ReAct thought → action |
| `observe` | `executor_skill` / DAI 子節點 | observation 摘要 |
| `fuse` | `replan_llm` | finish 整理說明 |

### 範例（輪詢中）

```json
{
  "flow": "chat",
  "stage": "execute",
  "headline_zh": "執行 · call_dai",
  "nodes": [ "..." ],
  "thinking": {
    "collapsed_default": false,
    "entries": [
      {
        "id": "tf-1",
        "phase": "message_features",
        "node_id": "ingress",
        "label_zh": "理解訊息",
        "summary_zh": "您想確認是否為詐騙，並提到是媽媽收到的；已抽出待審正文。",
        "status": "done",
        "ts": "2026-09-01T14:30:01+08:00"
      },
      {
        "id": "tf-2",
        "phase": "plan",
        "node_id": "planner_llm",
        "label_zh": "規劃任務",
        "summary_zh": "已有可審正文，需工具调用進行風險分析。",
        "action": { "type": "tool", "skill": "call_dai", "brief_zh": "送 DAI 雙路分析" },
        "status": "done",
        "ts": "2026-09-01T14:30:03+08:00"
      },
      {
        "id": "tf-3",
        "phase": "observe",
        "node_id": "dai_path_a",
        "label_zh": "風險分析",
        "summary_zh": "Path A 判定為中高風險，含銀行冒充與連結特徵。",
        "observation_zh": "risk_score=78",
        "status": "active",
        "ts": "2026-09-01T14:30:05+08:00"
      }
    ]
  }
}
```

---

## 完成後仍可查看

現況：`finally: clear_pipeline_stage()` 會清空 pipeline，輪詢結束後思考過程消失。

### 方案（定案）

1. **輪詢期間**：`policy_state.pipeline.thinking` 隨執行追加  
2. **本輪結束**：把 `thinking.entries` **複製**到 chat 回應與 session  
3. **API**：`POST /v1/chat`、`/v1/review` 回應追加可選欄位 `thinking_trace`（與 pipeline 同 schema 的 entries）

```json
{
  "answer": "此則簡訊風險偏高…",
  "thinking_trace": [ "..." ]
}
```

App 在該則 assistant 訊息上顯示「查看思考過程」折疊區（不需再輪詢）。

---

## 後端實作

### 模組

| 模組 | 職責 |
|------|------|
| `cai/pipeline_progress.py` | 擴充 `append_thinking_entry()`、`get_pipeline_status()` 帶出 `thinking` |
| `cai/hybrid/thinking_display.py`（新） | 把 MessageFeatures / ReAct 結構 **轉成** `summary_zh`（消毒、限長） |
| `plan_execute.py` / `react_replan.py` | 各階段 hook 寫 thinking entry |
| `mobile_server.py` | 回應帶 `thinking_trace`；**不清** thinking 直到寫入 response |

### 摘要生成規則（不暴露 raw prompt）

| 來源 | `summary_zh` 怎麼來 |
|------|---------------------|
| MessageFeatures | 模板 + 關鍵欄位：`primary_goal`、`has_reviewable_body`、`relation_label` |
| Planner | LLM 輸出可選 `rationale_zh`（≤120 字）或後處理模板 |
| ReAct | 使用 `thought` 欄位，經 `sanitize_thinking_text()` 去 PII、限 200 字 |
| DAI | 既有 risk 摘要，不含內部 DAG 技術名 |

**禁止**寫入：完整 system prompt、Profile 全量 JSON、artifact 全文（可用「已收到 N 字正文」代替）。

### 與現有 `nodes[]` 對齊

Hybrid H3 節點命名可漸進調整，**舊 id 保留 alias**：

| 現有 node id | Hybrid 新 id（可並存） |
|--------------|------------------------|
| `ingress` | `ingress` |
| — | `nlp_features`（新增，可插在 ingress 後） |
| `planner_llm` | `planner_llm` |
| `replan_llm` | `react_thought` / `react_action`（ReAct 時拆兩 entry） |
| `executor_skill` | `observe` |

流程圖節點數**不必**與 thinking 條數 1:1；一個 node 可有多條 thinking entry（如 ReAct 多步）。

---

## 手機 App 變更（smsagent）

| 檔案 | 變更 |
|------|------|
| `PipelineModels.kt` | 加 `ThinkingEntry`、`PipelineProgress.thinking` |
| `DualAgentApi.kt` | 解析 `thinking` / `thinking_trace` |
| `ThinkingProcessPanel.kt`（新） | 折疊列表渲染 entries |
| `ChatScreen.kt` | busy 時：Flowchart **上** + Thinking **下**；完成後 message 可展開 trace |
| `ChatApiResponse` | 可選 `thinkingTrace` |

舊 App 不解析新欄位 → 行為與現今相同。

---

## 與 TurnTrace 的關係

| 對象 | 用途 |
|------|------|
| **TurnTrace**（[Hybrid-反饋與優化.md](./Hybrid-反饋與優化.md)） | 離線除錯、scenarios、mismatch |
| **thinking.entries** | **使用者可讀**即時展示 |

可從同一 hook 分叉：`TurnTrace` 存完整結構，`thinking` 只存消毒摘要。

---

## 實作順序（併入 Phase H3）

1. `thinking_display.py` + `append_thinking_entry`  
2. `message_features` / Planner / ReAct hook 寫 entry  
3. `GET /pipeline` 回傳 `thinking`  
4. chat/review 回應帶 `thinking_trace`  
5. smsagent UI：ThinkingProcessPanel + 完成後展開  
6. 更新 `MOBILE.md`、`test_pipeline_progress.py`

---

## 變更紀錄

| 日期 | 說明 |
|------|------|
| 2026-09-01 | 初版：保留流程圖 + thinking.entries API + 完成後 thinking_trace |
