"""Guard 管線：改為 risk_analysis；mock 不依賴 Ollama。"""

from __future__ import annotations

import os
from unittest.mock import patch

from dual_agent.dai.guard_pipeline import run_guard_analysis_pipeline
from dual_agent.dai.schemas import DAIRequest


def _fake_report() -> dict:
    return {
        "risk_score": 60,
        "risk_score_total": 60,
        "r_final_machine": 60,
        "verdict": "allow",
        "gate_tier": "allow",
        "dominant_source": "r_rules",
        "component_scores": {
            "r_rules": 25,
            "r_threat_intel": 0,
            "r_tls": 0,
            "r_toxic_fused": 0,
            "r_llm_optional": 0,
            "r_ueba": 10,
        },
        "evidence": [],
        "reason_highlights": ["test"],
        "track_a": {"tier_scores": {}, "matched_rules": [], "missing_evidence": []},
        "safety_summary": "測試",
        "archive_note": "測試",
        "labels": [],
        "risk_fusion": {"mode": "max_component", "r_final": 60, "risk_total": 60},
        "semantic": {"skipped": True},
        "pipeline_phases": ["rules"],
        "recommended_cai_action": "continue",
        "risk_user": {"risk_total_user_fused": 60, "delta_user": 0},
        "risk_score_total_user_fused": 60,
    }


@patch("dual_agent.dai.guard_pipeline.run_risk_analysis")
def test_run_guard_analysis_pipeline_delegates(mock_run: object) -> None:
    mock_run.return_value = _fake_report()
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "0"}, clear=False):
        out = run_guard_analysis_pipeline(DAIRequest(user_text="hello", artifact=""))
    mock_run.assert_called_once()
    assert out["risk_score"] == 60
    assert out["component_scores"]["r_rules"] == 25
    assert out["gate_tier"] in ("allow", "warn", "block")
