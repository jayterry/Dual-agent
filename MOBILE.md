# smsagent × Dual-agent 手機 Demo

## 架構

| 操作 | API | 後端 |
|------|-----|------|
| 送審 | `POST /v1/review` | `run_dai_then_replan`（DAI → Replan，不經 Planner） |
| 追問 | `POST /v1/chat` | `run_plan_and_execute`（完整 CAI） |
| 流程進度（輪詢） | `GET /v1/session/{session_id}/pipeline` | `policy_state.pipeline` |
| 信任網站 | `/v1/trust/domains` | `dual_agent/dai/user_db.py`（UEBA） |

### 流程進度輪詢

App 在 `POST /v1/chat` 或 `/v1/review` 等待期間，約每 400ms 呼叫：

`GET /v1/session/{session_id}/pipeline`

回傳欄位：

| 欄位 | 說明 |
|------|------|
| `flow` | `chat` \| `review` |
| `stage` / `steps[]` | 粗粒度 5／3 步（向後相容） |
| `nodes[]` | 流程圖節點（對齊 `flow.md`） |
| `current_node_id` | 目前 active 節點 id |
| `headline_zh` | 單行摘要，如 `Planner · qwen2.5:7b` |
| `label_zh` / `detail_label_zh` | 粗粒度文案與 skill 副標 |

`nodes[]` 每項：`id`、`kind`（`system` \| `llm` \| `skill` \| `dai_step`）、`label_zh`、`model`（LLM 時）、`skill`（執行技能時）、`status`（pending \| active \| done）。

**Chat 粗步驟**：理解訊息 → 記憶判斷 → 規劃任務 → 執行技能 → 整理回覆  

**Chat 流程圖節點（精細）**：載入上下文 → Memory Manager（3b）→ Planner（7b）→ 執行技能 →（若 `call_dai`）DAI Defense + DAG 7 步 → Replan（7b）

**Review 粗步驟**：風險分析 → 整理回覆 → 完成

**Review 流程圖節點**：載入上下文 → DAI Defense → DAG 7 步 → Replan → 完成

## PC 端啟動

```bash
cd Dual-agent
# 需 Ollama 運行中（預設 http://127.0.0.1:11434）
pip install -r requirements.txt
uvicorn mobile_server:app --host 127.0.0.1 --port 8787
```

## 手機連線

實機 USB：

```bash
adb reverse tcp:8787 tcp:8787
```

App 內 `DualAgentApi.API_BASE` 預設 `http://127.0.0.1:8787`。  
模擬器請改為 `http://10.0.2.2:8787`。

## Android 專案

路徑：`AndroidStudioProjects/smsagent`

- GPT 風格對話：`ui/ChatScreen.kt`
- 通知攔截：`NotifListener.kt`（不變）
- 信任網站管理：TopAppBar → 信任網站

## 環境變數（可選）

| 變數 | 說明 |
|------|------|
| `USER_DB_PATH` | UEBA JSON 路徑（預設 `./user_profile_db.json`） |
| `AGENT_API_TOKEN` | 設定後 App 需 Bearer token |
| `MOBILE_SESSION_TTL_SEC` | Session 快取 TTL（預設 7200） |

## 桌面版

`desktop_cai_app.py` 仍使用 `run_plan_and_execute`，不受送審雙軌影響。
