# smsagent × Dual-agent 手機 Demo

## 架構

| 操作 | API | 後端 |
|------|-----|------|
| 送審 | `POST /v1/review` | `run_dai_then_replan`（DAI → Replan，不經 Planner） |
| 追問 | `POST /v1/chat` | `run_plan_and_execute`（完整 CAI） |
| 信任網站 | `/v1/trust/domains` | `dual_agent/dai/user_db.py`（UEBA） |

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
