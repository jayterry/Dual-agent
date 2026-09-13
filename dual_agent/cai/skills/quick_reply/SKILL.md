---
name: quick_reply
description: 問候、身份、道謝、能力說明與超出範圍的確定性短回覆。NLP 標 assistant_chat 或 out_of_scope 時使用，不呼叫 LLM。
risk_level: low
requires_confirmation: false
aliases: [smalltalk, decline_oos]
---

# quick_reply

## Purpose
給不需工具的短對話填模板回覆（問候、我是誰／你是誰、謝謝、能做什麼、超出範圍）。

## Inputs
- kind: string（greet | thanks | capability | identity_user | identity_assistant | out_of_scope）
  缺省時由本輪 MessageFeatures 的 domain_tags／primary_goal 推斷。

## Outputs
`SkillResult.summary` 為給使用者看的全文；`data.kind` 為實際採用的種類。
