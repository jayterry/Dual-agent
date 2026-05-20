# Dual-agent Skills 對照矩陣

本文件由 `scripts/generate_skills_matrix.py` 自動產生，對照：

- **Catalog**：[`Agent Skills Added.md`](../Agent%20Skills%20Added.md)
- **Registry**：`dual_agent/cai/skills_registry.py`

產生時間（UTC）：2026-05-20 12:17

## 摘要

| 指標 | 數值 |
|------|------|
| CAI registry | 9 |
| DAI registry | 1 |
| Catalog CAI 列 | 16 |
| Catalog DAI 列 | 19 |

**狀態**：`已實作` = registry 或 risk_analysis 管線；`規劃中` = 僅出現在 Catalog。

## 1. Helpful (CAI)

| Catalog 名稱 | 用途（摘要） | 狀態 | 備註 |
|-------------|-------------|------|------|
| `search_web` | Search the internet for info | 已實作 | registry |
| `fetch_url` | Fetch data/file from a URL | 已實作 | registry |
| `instant_answer` | Get a quick factual answer | 已實作 | registry |
| `ask_user` | Ask the user for more information | 已實作 | registry |
| `open_app` | Launch a local desktop application | 已實作 | registry |
| `open_url` | Open a URL in browser | 已實作 | registry |
| `summarize_text` | Summarize long text | 規劃中 | — |
| `schedule_task` | Add a reminder/calendar event | 規劃中 | — |
| `translate_text` | Translate input to another language | 規劃中 | — |
| `extract_info` | Pull structured info from text | 規劃中 | — |
| `read_file` | Read content of a specified local file | 規劃中 | — |
| `qa_over_file` | Answer questions about a file’s content | 規劃中 | — |
| `summarize_file` | Summarize the content of a file | 規劃中 | — |
| `search_local_files` | Search local files for a term | 規劃中 | — |
| `copy_to_clipboard` | Copy text to the clipboard | 規劃中 | — |
| `paste_from_clipboard` | Paste text from the clipboard | 規劃中 | — |

## 2. Protective (DAI)

| Catalog 名稱 | 用途（摘要） | 狀態 | 備註 |
|-------------|-------------|------|------|
| `call_dai` | Trigger DAI risk/safety/compliance review | 已實作 | registry |
| `risk_analysis` | Analyze risk of planned action/text | 已實作 | dual_agent/dai/risk_analysis (run_risk_analysis) |
| `policy_check` | Check for rules/policy violations | 規劃中 | — |
| `guarded_retrieval` | Info retrieval with enforced safety/policy check | 規劃中 | — |
| `threat_detection` | Scan for threats in input/content | 規劃中 | — |
| `sanitize_input` | Clean/filter dangerous/sensitive content | 規劃中 | — |
| `secure_ingest` | Review and add new knowledge/content | 規劃中 | — |
| `quarantine` | Mark suspicious input for later review | 規劃中 | — |
| `block_action` | Prevent execution of risky/forbidden skills | 規劃中 | — |
| `log_security_event` | Record security-relevant events for auditing | 規劃中 | — |
| `extract_urls` | Extract all URLs from text | 已實作（管線） | risk_analysis URL extraction |
| `check_url_reputation` | Check if URL is malicious via threat intelligence | 已實作（管線） | risk_analysis providers (placeholder) |
| `pii_detection` | Detect personally identifiable info in content | 已實作（管線） | rules.py partial (ID patterns) |
| `content_moderation` | Flag offensive/harmful/NSFW language | 已實作（管線） | toxic_score / Chroma |
| `file_type_filter` | Allow/block certain file types | 規劃中 | — |
| `dependency_check` | Validate libraries/dependencies are trusted | 規劃中 | — |
| `suspicious_process_check` | Look for suspicious processes on the local system | 規劃中 | — |
| `audit_log_export` | Export critical/flagged actions for auditing | 規劃中 | — |
| `enforce_confirmed_skills_only` | Allow only whitelisted skills without confirmation | 規劃中 | — |

## 3. Hybrid / Patterns

| Catalog 名稱 | 用途（摘要） | 狀態 | 備註 |
|-------------|-------------|------|------|
| `approval_by_policy` | Enforce multi-layered policy on actions | 規劃中 | — |
| `cross_agent_validation` | Require agreement from both CAI and DAI | 規劃中 | — |
| `reputation_blacklist` | Auto-flag/block by syncing with online blacklists | 規劃中 | — |
| `contextual_protections` | Adjust risk tolerance by user history/context | 規劃中 | — |
| `auto_patch` | Suggest or apply safer code/patches if risk detected | 規劃中 | — |

## 4. Advanced Features

| Catalog 名稱 | 用途（摘要） | 狀態 | 備註 |
|-------------|-------------|------|------|
| `LLM_chain_of_thought` | Show explicit step-by-step intermediate reasoning | 規劃中 | — |
| `plugin_system` | Allow users to install or enable new skills | 規劃中 | — |
| `self_healing` | DAI can auto-recover/restart/rollback as needed | 規劃中 | — |
| `continuous_learning` | Retrain/adjust on incident logs, feedback, audits | 規劃中 | — |
| `user_profile_management` | CAI adapts plans/skills based on user profile | 規劃中 | — |

## 5. Registry 有、Catalog 未列

| 名稱 | 用途 | 狀態 | 備註 |
|------|------|------|------|
| `confirm` | — | 已實作 | registry only (CAI) |
| `weather` | — | 已實作 | registry only (CAI) |
| `approve` | — | 已實作 | alias → `confirm` |
| `cancel` | — | 已實作 | alias → `confirm` |
| `wttr` | — | 已實作 | alias → `weather` |
| `天氣` | — | 已實作 | alias → `weather` |
| `氣象` | — | 已實作 | alias → `weather` |

## 重新產生

```bash
python scripts/generate_skills_matrix.py
```
