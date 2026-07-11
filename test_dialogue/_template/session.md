# 測試對話：{問題簡述}

| 項目 | 內容 |
|------|------|
| 日期 | YYYY-MM-DD |
| 測試者 | Cursor / 人工 |
| 環境 | 桌面 app 或 `POST /v1/chat`；Ollama 型號 |
| Session | 新開對話／延續上一輪 |
| 對應問題 | `test_reports/xxx/` |

## 對話（同一 session，依序輸入）

**劇本原則**：先重跑歷史對話（baseline），再接實驗組（experimental）延伸句；對照組（control）用獨立 session。

| # | 組別 | 測試者 → Dual-agent | Dual-agent 計畫步驟 | Dual-agent 回覆摘要 | 備註 |
|---|------|---------------------|---------------------|---------------------|------|
| 1 | baseline | | | | 重現歷史對話 |
| 2 | experimental | | | | 延伸探測 |
| 3 | control | | | | 獨立 session 對照 |
