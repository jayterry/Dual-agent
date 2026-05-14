---
name: run_guard_pipeline
description: >-
  Runs the DAI fixed-order pipeline (Defense single-scan, optional toxic fusion, gate tier) on
  user_text or artifact. Use when the user pastes external messages, before memory ingestion, or
  when the planner needs a structured risk report for DAI.
risk_level: high
requires_confirmation: false
---

# run_guard_pipeline

執行 `dual_agent.dai.guard_pipeline.run_guard_analysis_pipeline`；需本機 Ollama 可連線（Defense 與可選 embedding）。
