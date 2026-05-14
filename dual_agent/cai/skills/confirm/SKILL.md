---
name: confirm
description: 用於在執行高風險或需確認的計畫前，讓使用者明確同意或取消。當系統提示「需要確認」後使用者回覆「確認/取消」時使用。
risk_level: low
requires_confirmation: false
aliases: [approve, cancel]
---

# Confirm

## Purpose
在同一個桌面 session 中，批准或取消上一個「待確認的計畫」。

## Inputs
- action: string（approve | cancel）

## Outputs
Return `SkillResult`，並更新 `ctx.policy_state` 的 pending plan 狀態。

