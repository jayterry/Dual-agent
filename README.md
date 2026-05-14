# Dual-agent

`Dual-agent` 是一個以 CAI / DAI 雙層架構為核心的本地 AI 專案，用來處理任務導向對話、風險審查與安全分析流程。

## 主要內容

- `dual_agent/`: 核心程式碼
- `tests/`: 測試
- `desktop_cai_app.py`: 桌面版 CAI 介面
- `flow.md`: 流程與架構說明

## 安裝

```bash
pip install -r requirements.txt
```

## 執行

```bash
python desktop_cai_app.py
```

## 測試

```bash
python -m pytest
```

## 備註

- 專案依賴 Ollama 與 LangChain 相關套件。
- 詳細流程可參考 `flow.md`。
