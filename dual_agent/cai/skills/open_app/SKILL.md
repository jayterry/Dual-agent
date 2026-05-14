---
name: open_app
description: 在 Windows 啟動本機程式（例如 Chrome/Edge/記事本），支援用別名或直接給 exe 路徑。當使用者要求「打開某個程式」時使用。
risk_level: medium
requires_confirmation: true
aliases: [launch, start_app]
---

# Open App (Windows)

## Purpose
啟動本機程式（不下載、不安裝、不修改系統設定）。

## Inputs
- name: string（選填，程式別名，例如 chrome/edge/notepad）
- path: string（選填，exe 完整路徑；優先於 name）

## Outputs
Return `SkillResult`，其中 `data.path` 可能包含解析到的可執行檔路徑。

