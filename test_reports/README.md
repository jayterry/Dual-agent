# CAI 測試回報索引

依**已知問題**分資料夾；內含分析、`scenarios.json`、審計 JSON。  
**與 Dual-agent 的測試對話**（測試劇本本體）見 [`test_dialogue/`](../test_dialogue/)（資料夾名稱對齊）。

完整循環（提方案 → 沙盒 → 驗收 → git → 新模組 → 對話測試 → debug）見 [`docs/VERIFICATION_WORKFLOW.md`](../docs/VERIFICATION_WORKFLOW.md)。

| 資料夾 | 主要問題 | 狀態 | 最後審計 |
|--------|----------|------|----------|
| [`agent_full_coverage`](./agent_full_coverage/) | 全流程煙霧測試（Ingress／Router／CAI／DAI／Memory） | **open** | 2026-07-12 |
| [`pending_review_無法取消`](./pending_review_無法取消/) | 拒絕送審或改話題後 `pending_review` 未清除 | **已修** | 2026-07-12 |

## 新增問題回報

1. 複製 [`_template/`](./_template/) 為 `test_reports/<問題簡述>/`
2. 在 [`test_dialogue/<問題>/`](../test_dialogue/) 記錄與 Dual-agent 的測試對話
3. 依對話摘出失敗輪次，寫入 `scenarios.json`
4. 修復後將 `status` 改為 `fixed`，審計會跳過該問題

## 重跑審計

```bash
python scripts/run_problem_reports_audit.py
```

結果寫入各問題資料夾的 `audit_latest.json`。

## scenario 類型

| type | 用途 |
|------|------|
| `plan_execute_multiturn` | 多輪 session（mock LLM），驗證 `pending_review`、plan skills |
| `validate` | 單輪 `validate_planner_output` |
| `ingress` | `normalize_ingress` 邊界 |
| `semantic_router` | router / apply 覆寫 |
| `memory_multiturn` | 記憶記住／確認／回想（mock parse_fn） |

詳見 [`_template/scenarios.json`](./_template/scenarios.json)。
