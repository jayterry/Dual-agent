---
name: open_url_readonly
description: 以唯讀方式用預設瀏覽器開啟 http/https 網址（可用於開啟搜尋結果、官方網站等）。當使用者要求「打開某個網址」時使用。
risk_level: low
requires_confirmation: false
aliases: [open_url, url, open, goto]
---

# Open URL (Readonly)

## Purpose
開啟網址（只做開啟，不做表單提交或自動互動）。

## When to use
- 使用者提供明確網址
- 或要求開啟網站（可用少量網站別名）

## Inputs
- url: string（必填，http/https 或網站別名）

## Outputs
Return `SkillResult`：`ok/summary/data`，其中 `data.url` 會回傳實際開啟的 URL。

