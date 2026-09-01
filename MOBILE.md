# smsagent × ScamSentinel 手機 Demo

## 架構

| 操作 | API | 後端 |
|------|-----|------|
| 送審 | `POST /v1/review` | `run_dai_then_replan`（DAI 雙路徑 → Replan） |
| 追問 | `POST /v1/chat` | `run_plan_and_execute`（完整 CAI） |
| 風險檔案 | `GET`／`PUT /v1/profile` | `dual_agent/cai/profile_store.py`（四欄） |
| 流程進度（輪詢） | `GET /v1/session/{session_id}/pipeline` | `policy_state.pipeline` |
| 信任網站 | `/v1/trust/domains` | `dual_agent/dai/user_db.py`（UEBA） |

### 風險檔案（與桌面對齊）

App 本機與後端同步四欄（關係／管道由系統推斷，不送）：

| 欄位 | 說明 |
|------|------|
| `age_band` | `<25` / `25-39` / `40-59` / `60+` |
| `occupation` | `student` / `office` / `freelance` / `retired` / `other` |
| `primary_apps` | 逗號或陣列，如 `SMS,LINE`（作管道推斷先驗） |
| `invest_exp` | 選填文字 |

`POST /v1/review`、`/v1/chat` 的 `user_profile` 可一併帶四欄；後端會 `upsert` 並寫入 `policy_state.dai_persona`／`profile_user_id`。

風險卡對應回傳 `dai.path_a`（威脅／情境分數）、`relation_inferred`、`channel_inferred`，閘道分數為 `max(threat, context)`。

### 流程進度輪詢

App 在 `POST /v1/chat` 或 `/v1/review` 等待期間，約每 400ms 呼叫：

`GET /v1/session/{session_id}/pipeline`

回傳欄位：

| 欄位 | 說明 |
|------|------|
| `flow` | `chat` \| `review` |
| `stage` / `steps[]` | 粗粒度步驟（向後相容） |
| `nodes[]` | 流程圖節點 |
| `current_node_id` | 目前 active 節點 id |
| `headline_zh` | 單行摘要，如 `Planner · qwen2.5:7b` |
| `label_zh` / `detail_label_zh` | 粗粒度文案與 skill 副標 |

`nodes[]` 每項：`id`、`kind`（`system` \| `llm` \| `skill` \| `dai_step`）、`label_zh`、`model`（LLM 時）、`skill`（執行技能時）、`status`（pending \| active \| done）。

**Chat 粗步驟**：理解訊息 → 記憶判斷 → 規劃任務 → 執行技能 → 整理回覆  

**Chat 流程圖節點**：載入上下文 → Memory Manager → Planner → 執行技能 →（若 `call_dai`）DAI 啟動 → 推斷管道／關係 → Path A → Path B → Narrator → Replan  

**Review 粗步驟**：雙路風險分析 → 整理回覆 → 完成

**Review 流程圖節點**：載入上下文 → DAI 啟動 → 推斷管道／關係 → Path A 威脅／情境 → Path B（LLM）→ Narrator → Replan → 完成

風險卡呈現 **威脅／情境** 兩分並排；`risk_score`（閘道＝max）僅作 CAI 動作門檻次要說明。

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

App 內 `ScamSentinelApi.API_BASE` 預設 `http://127.0.0.1:8787`。  
模擬器請改為 `http://10.0.2.2:8787`。

## Android 專案

路徑：`AndroidStudioProjects/smsagent`

- 對話：`ui/ChatScreen.kt`
- 風險檔案：`ui/ProfileEditScreen.kt`（四欄）
- 通知攔截：`NotifListener.kt`
- 信任網站管理：TopAppBar → 信任網站

## 環境變數（可選）

| 變數 | 說明 |
|------|------|
| `USER_DB_PATH` | UEBA JSON 路徑（預設 `./user_profile_db.json`） |
| `AGENT_API_TOKEN` | 設定後 App 需 Bearer token |
| `MOBILE_SESSION_TTL_SEC` | Session 快取 TTL（預設 7200） |

## 桌面版

`desktop_cai_qt.py`／`desktop_cai_app.py` 使用相同 `profile_store` 與雙路徑 DAI。
