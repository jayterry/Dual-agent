---
name: search_web
description: 以預設瀏覽器開啟搜尋結果頁（不抓內容）。當使用者要「搜尋某個關鍵字」或你需要快速查詢資料來源時使用。
risk_level: low
requires_confirmation: false
aliases: [search, web_search]
---

# Search Web

## Purpose
把 query 組成搜尋引擎 URL 並開啟。

## Inputs
- query: string（必填）
- engine: string（選填，bing | google | duckduckgo；預設 bing）

## Outputs
Return `SkillResult`，其中 `data.url` 會回傳開啟的搜尋 URL。

