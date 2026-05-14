---
name: weather
description: 查詢指定地點目前天氣與簡短預報（wttr.in，免金鑰）。當使用者問氣溫、降雨、風力或旅行天氣時優先於 search_web。
risk_level: low
requires_confirmation: false
aliases: [wttr, 天氣, 氣象]
---

# Weather（wttr.in）

能力改寫自 OpenClaw 內建 skill `weather`（以 wttr.in 為資料來源），於 Dual-agent 以 Python 直接拉取，無需本機安裝 `curl`。

## Inputs

- `location`（必填）：城市、地區、機場代碼（如 `KEF`、`Reykjavik`、`台北`）。
- `format`（選填）：`brief`（單行，預設）或 `json`（結構化目前＋今日預報摘要）。

## Outputs

`SkillResult.data` 含 `source`（wttr.in）、`location`、`format`，以及 `text` 或 `json` 片段。
