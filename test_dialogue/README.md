# 與 Dual-agent 的測試對話

**測試者**：Cursor（或人工）透過桌面 app / `mobile_server` 與 **CAI（Dual-agent）** 實際對話的紀錄。  
這些對話本身就是測試劇本與重現依據。

與 [`test_reports/`](../test_reports/) **分開**：

| 資料夾 | 內容 |
|--------|------|
| `test_dialogue/<問題>/` | **怎麼跟 Dual-agent 聊**（逐輪輸入、計畫步驟、回覆） |
| `test_reports/<問題>/` | **問題分析**（根因、審計 JSON、`scenarios.json`、修復建議） |

同一問題兩邊**資料夾名稱對齊**（例如 `pending_review_無法取消`）。

## 索引

| 問題 | 對話紀錄 | 對應回報 |
|------|----------|----------|
| pending_review 無法取消 | [`2026-07-12_Cursor測試_2.md`](./pending_review_無法取消/2026-07-12_Cursor測試_2.md) 等 | [`test_reports/pending_review_無法取消/`](../test_reports/pending_review_無法取消/) |
| meta 誤觸搜尋（已修） | [`meta_誤觸搜尋/`](./meta_誤觸搜尋/) | （無獨立回報；修正後以 pytest 回歸） |

## 新增一筆測試對話

1. 在 `test_dialogue/<問題>/` 新增 `YYYY-MM-DD_Cursor測試.md`（可複製 [`_template/session.md`](./_template/session.md)）
2. 記錄：環境、**baseline 歷史對話**、**experimental 延伸**、**control 對照**（獨立 session）
3. 若確認為 bug → 在 `test_reports/<問題>/` 更新 `scenarios.json` 並跑 `python scripts/run_test_dialogue.py`
