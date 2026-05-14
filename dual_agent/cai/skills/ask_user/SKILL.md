---
name: ask_user
description: 當資訊不足、無法安全規劃下一步時，用一個明確問題向使用者追問（例如請貼上簡訊全文/來源/是否點過連結）。在不確定時優先使用，而不是任意呼叫其他技能。
risk_level: low
requires_confirmation: false
aliases: [clarify, question]
---

# Ask User

## Purpose
在工具/技能不足以安全前進時，主動向使用者追問必要資訊，避免誤用工具造成風險。

## Inputs
- question: string（必填，要問使用者的問題）
- rationale: string（選填，為什麼需要這個資訊；會顯示給使用者）

## Outputs
Return `SkillResult`，其中 `data.question` 與 `data.rationale` 供 UI 顯示；並把 `ctx.policy_state["pending_user_question"]` 設為該 question。

