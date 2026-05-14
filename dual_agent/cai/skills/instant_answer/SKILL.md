---
name: instant_answer
description: 以 DuckDuckGo Instant Answer API 取得短摘要／定義（免金鑰、無瀏覽器）。適合「某某是什麼」等可即答條目；若無摘要再改用 search_web。
risk_level: low
requires_confirmation: false
aliases: [ddg_instant, 即時百科, quick_fact]
---

# Instant Answer（DuckDuckGo）

非 OpenClaw 原件；作為精簡查詢補強，與僅開分頁的 `search_web` 分擔情境。

## Inputs

- `query`（必填）：要查的詞組或短句。

## Outputs

`SkillResult.data` 含 `heading`、`abstract`、`url`（若 API 提供）與原始欄位摘要。
