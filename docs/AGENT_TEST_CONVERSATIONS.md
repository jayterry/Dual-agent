# CAI 測試工作流

> **完整驗證循環**（提方案 → 沙盒 → 驗收 → git → 新模組 → 對話測試 → debug）見 [`VERIFICATION_WORKFLOW.md`](./VERIFICATION_WORKFLOW.md)。

三層分工：

| 位置 | 內容 |
|------|------|
| [`test_dialogue/`](../test_dialogue/) | **測試者（Cursor／人工）與 Dual-agent 的對話** — 測試劇本本體 |
| [`test_reports/`](../test_reports/) | **發現的問題** — 根因、審計、`scenarios.json` |
| 本檔 | 工作流說明與 Session 登錄模板 |

---

## 流程

### 1. 與 Dual-agent 對話（測試）

- 環境：桌面 app 或 `mobile_server` + Ollama（真實 E2E），或 mock 管線審計（無 Ollama）
- **同一 session** 連續輸入，記錄每輪：你的句子 → Dual-agent 計畫步驟 → 回覆
- 寫入 `test_dialogue/<問題>/YYYY-MM-DD_<環境>.md`

### 2. 若確認為 bug

- 建 `test_reports/<問題>/`（名稱與 `test_dialogue` 對齊）
- 寫 `測試回報.md`、從對話摘 `scenarios.json`
- **劇本設計**：先將歷史對話標為 `baseline`，再補 `experimental` 延伸句與 `control` 對照組（獨立 session）
- 跑 `python scripts/run_test_dialogue.py` 或 `python scripts/run_problem_reports_audit.py`

### 3. 修復後

- `scenarios.json` 的 `status` → `"fixed"`
- 在 `test_dialogue` 補一筆修復後對話（可選）

---

## 自動審計（不需 Ollama）

```bash
python scripts/run_problem_reports_audit.py
```

讀 `test_reports/*/scenarios.json`（內容應源自 `test_dialogue` 的失敗輪次）。

---

## Session 登錄模板

```markdown
### Session YYYY-MM-DD — 簡短標題

| 項目 | 內容 |
|------|------|
| 對話紀錄 | test_dialogue/xxx/ |
| 問題回報 | test_reports/xxx/ |
| 環境 | Ollama / mock |
```

---

## 給 Cursor 的約定

1. 測 Dual-agent 時，對話寫入 `test_dialogue/<問題>/`
2. 分析與審計寫入 `test_reports/<問題>/`
3. 勿把「Cursor 與使用者的協作聊天」當成測試對話
4. **每次測試**：`scenarios.json` 先含歷史對話（`group: baseline`），再追加 `experimental` 與 `control` 句；用 `python scripts/run_test_dialogue.py` 產出對話紀錄
