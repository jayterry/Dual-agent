---
name: call_dai
description: 呼叫 DAI 防禦代理審查內容（簡訊審查：Defense LLM 規劃後，由 DAI Executor 跑固定 DAG：build_analysis_payload → fuse_risk_and_ueba）。當使用者要審簡訊、辨識詐騙簡訊時使用；待審全文放 args.artifact。
risk_level: medium
requires_confirmation: false
aliases: [dai, 簡訊審查, 審簡訊, dai審查]
---

# call_dai

由 CAI Executor 呼叫 `invoke_dai`，把結果寫入 `SkillResult.data`，供 Replan 產生給使用者的回答。

## Inputs

- `artifact`（強烈建議）：待審內文（簡訊全文、貼上的訊息）。
- `user_text`（選填）：使用者意圖短句；未填時使用對話輸入。
- `context_pack`（選填）：長脈絡摘要，對齊 CAI Context Pack。
- `sms_review`（選填，預設 `true`）：`true` → Defense 單次計畫 + DAI Executor 固定 7 步 DAG；`false` → Defense 多輪逐步迴圈。

若未提供 `artifact`，會退回使用本輪使用者輸入全文當待審內容（方便整段貼上）。

若內容僅為「我收到一則簡訊」等占位句、尚無可審正文，本技能會拒絕執行並回報錯誤碼 `artifact_meta_only`（Planner 應改排 `ask_user` 索取全文）。
