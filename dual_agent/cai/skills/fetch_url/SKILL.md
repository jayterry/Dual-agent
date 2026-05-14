---
name: fetch_url
description: 以 HTTP(S) 讀取公開網址內容並回傳精簡純文字（供模型閱讀），用於「讀取網頁／文章／公告」；不開瀏覽器。不可取代需登入或動態渲染之頁面。
risk_level: medium
requires_confirmation: false
aliases: [read_url, http_get, 讀取網址, 抓取網頁]
---

# Fetch URL

與 `open_url_readonly`（僅開分頁）不同：本 skill 會把回應本文摘錄寫入執行結果，讓 Planner／Replan 能依**實際內容**回答。

## 限制與安全

- 僅 **http/https**；會阻擋解析到 **內網／本機 IP** 的位址（反 SSRF）。
- 單次下載量與輸出字數有上限；**不**處理需要 Cookie／OAuth 的內容。
- 若為 HTML，會粗略去除標籤保留可讀文字；JSON 則嘗試美化為文字。

## Inputs

- `url`（必填）：完整 https 網址。
- `max_chars`（選填）：輸出給模型的文字上限，預設 12000。
