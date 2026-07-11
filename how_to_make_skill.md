完整的 Skill 目錄結構可能如下所示：

pdf/
├── SKILL.md              # 主要指令（觸發時載入）
├── FORMS.md              # 表單填寫指南（按需載入）
├── reference.md          # API 參考（按需載入）
├── examples.md           # 使用範例（按需載入）
└── scripts/
    ├── analyze_form.py   # 工具腳本（執行，不載入）
    ├── fill_form.py      # 表單填寫腳本
    └── validate.py       # 驗證腳本
模式 1：帶參考的高層次指南
---
name: pdf-processing
description: 從 PDF 文件中提取文字和表格、填寫表單並合併文件。在處理 PDF 文件或用戶提到 PDF、表單或文件提取時使用。
---

# PDF 處理

## 快速開始

使用 pdfplumber 提取文字：
```python
import pdfplumber
with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```

## 進階功能

**表單填寫**：完整指南請參閱 [FORMS.md](FORMS.md)
**API 參考**：所有方法請參閱 [REFERENCE.md](REFERENCE.md)
**範例**：常見模式請參閱 [EXAMPLES.md](EXAMPLES.md)
Claude 只在需要時載入 FORMS.md、REFERENCE.md 或 EXAMPLES.md。

模式 2：特定領域的組織
對於具有多個領域的 Skills，按領域組織內容以避免載入不相關的上下文。當用戶詢問銷售指標時，Claude 只需要讀取與銷售相關的模式，而不是財務或行銷數據。這使 token 使用量保持低水平，上下文保持集中。

bigquery-skill/
├── SKILL.md（概述和導航）
└── reference/
    ├── finance.md（收入、帳單指標）
    ├── sales.md（機會、管道）
    ├── product.md（API 使用、功能）
    └── marketing.md（活動、歸因）
SKILL.md
# BigQuery 數據分析

## 可用數據集

**財務**：收入、ARR、帳單 → 請參閱 [reference/finance.md](reference/finance.md)
**銷售**：機會、管道、帳戶 → 請參閱 [reference/sales.md](reference/sales.md)
**產品**：API 使用、功能、採用 → 請參閱 [reference/product.md](reference/product.md)
**行銷**：活動、歸因、電子郵件 → 請參閱 [reference/marketing.md](reference/marketing.md)

## 快速搜索

使用 grep 查找特定指標：

```bash
grep -i "revenue" reference/finance.md
grep -i "pipeline" reference/sales.md
grep -i "api usage" reference/product.md
```
模式 3：條件性細節
顯示基本內容，連結到進階內容：

# DOCX 處理

## 創建文件

使用 docx-js 創建新文件。請參閱 [DOCX-JS.md](DOCX-JS.md)。

## 編輯文件

對於簡單的編輯，直接修改 XML。

**對於追蹤更改**：請參閱 [REDLINING.md](REDLINING.md)
**對於 OOXML 詳情**：請參閱 [OOXML.md](OOXML.md)
Claude 只有在用戶需要這些功能時才讀取 REDLINING.md 或 OOXML.md。