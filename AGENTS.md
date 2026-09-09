# AGENTS.md

本文件供 AI 程式開發代理（Cursor、Cloud Agent 等）在本 repo 中改碼時遵循。

## 架構原則

- **不做向後相容。** 刪除過時路徑與程式，不要加相容層、fallback 或 migration。
- **最簡實作。** 選擇能完整滿足當前需求的最簡單做法；避免投機性的抽象、設定與間接層。
- **分層成長。** 從最小可端到端運作的版本開始，在已能運作的產品上逐層加能力；不要為未完成的複雜度犧牲現有可用功能。
- **模組化。** 元件職責清楚、邊界分明。
- **善用成熟函式庫。** 在能降低整體複雜度或提升可靠度時，優先採用維護良好的既有套件；沒有明確理由不要重造輪子。
- **先用專案既有依賴。** 在自寫實作或加新套件前，先查現有依賴的文件與型別，確認是否已支援所需能力。
- **長期架構決策。** 不接受「暫時湊合、之後再換」的權宜之計。

## 專案概覽

**Dual-agent** 是以 CAI / DAI 雙層架構為核心的本地 AI 系統：

| 代理 | 全名 | 職責 |
|------|------|------|
| **CAI** | Chat Agent Intelligence | 使用者互動、任務理解、Planner / Replan、Todo 編排、工具呼叫、最終回答 |
| **DAI** | Defense Agent Intelligence | 安全審核、風險分析、RAG 安全檢索、資料入庫審查、正規化與結構化 |

詳細架構見 [`project.md`](project.md)、[`flow.md`](flow.md)。

## 不可違反的架構邊界

1. **CAI 不得直接存取任何底層資料庫**（Vector DB、Quarantine DB、Safe Knowledge DB、Threat Memory DB、Policy DB 等）。需要知識檢索、風險分析或入庫審核時，必須透過 DAI interface（例如 `call_dai`）呼叫。
2. **DAI 是 RAG 與安全審核的唯一入口。** 檢索、風險分析、入庫審查、威脅比對、規則查詢、Quarantine 判斷皆須經 DAI。
3. **外部 raw data 必須先經 DAI 審查**（正規化、消毒、結構化、風險評分、入庫決策）後才能寫入任何 DB。

## 目錄結構

| 路徑 | 用途 |
|------|------|
| `dual_agent/cai/` | CAI 核心與技能（`skills/<name>/handler.py` + `SKILL.md`） |
| `dual_agent/dai/` | DAI 核心與技能（風險評分、guard pipeline 等） |
| `tests/` | pytest 測試 |
| `scripts/` | 訓練、評估、審計等一次性腳本 |
| `docs/` | 架構、風險評分、驗證流程等文件 |
| `desktop_cai_app.py` | 桌面版 CAI 介面入口 |

新增技能請遵循 [`how_to_make_skill.md`](how_to_make_skill.md) 的目錄慣例。

## 開發慣例

- **語言與風格：** Python；改碼前先讀周邊檔案，匹配既有命名、型別與抽象層級。
- **測試：** 改動核心邏輯後執行 `python -m pytest`；只加有實質行為覆蓋的測試，不為瑣碎斷言寫測試。
- **註解：** 程式應能自解；註解僅用於非顯而易見的業務邏輯或深層技術細節。
- **範圍控制：** 只做任務要求的變更；不順手重構、不加未請求的文件或設定。
- **依賴：** 優先使用 `requirements.txt` 中已有套件（Ollama、LangChain 等）；加新依賴需有明確理由。

## 參考文件

- [`README.md`](README.md) — 安裝與執行
- [`project.md`](project.md) — 架構邊界與流程設計
- [`docs/專案進度與目標.md`](docs/專案進度與目標.md) — 現行目標與進度
- [`docs/VERIFICATION_WORKFLOW.md`](docs/VERIFICATION_WORKFLOW.md) — 驗證與測試流程
- [`docs/RISK_SCORING.md`](docs/RISK_SCORING.md) — 風險評分模型
