"""semantic_labels 顯示分下限（融合 v2）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.rules import score_r_rules
from dual_agent.dai.risk_analysis.verdict import finalize_display_risk_score, summary_indicates_scam
from dual_agent.dai.schemas import DAIRequest

_IDENTITY_SMS = (
    "【重要通知】您尚未辦理簽署實名認證，帳戶將於今日凍結。"
    "請立即點擊連結完成認證，否則將停權。此為政府補助專案通知。"
)


def test_identity_rules_hit() -> None:
    res = score_r_rules(_IDENTITY_SMS)
    assert res.score >= 25
    assert any(h.rule_id == "identity_scam_framework" for h in res.hits)


def test_summary_indicates_scam() -> None:
    assert summary_indicates_scam("這則訊息可能涉及詐騙行為，建議提高警覺。")
    assert not summary_indicates_scam("一般帳單通知，請至官網查詢。")


def test_finalize_floor_from_phishing_label() -> None:
    score, _, _, floor, _ = finalize_display_risk_score(
        2,
        delta_user=2,
        r_rules=0,
        r_threat_intel=0,
        safety_summary="可能涉及詐騙行為，請勿輕信。",
        semantic_labels=["phishing"],
    )
    assert floor >= 60
    assert score >= 60


def test_pipeline_identity_rules_and_labels() -> None:
    req = DAIRequest(user_text="送審", artifact=_IDENTITY_SMS, sms_review=True)
    stub = {
        "r_llm_optional": 2,
        "tier_h": 8,
        "tier_i": 4,
        "explanation": "",
        "safety_summary": "可能涉及詐騙行為，特別是實名認證恐嚇，建議提高警覺。",
        "labels": ["phishing"],
        "skipped": False,
    }
    with patch(
        "dual_agent.dai.skills._pipeline_steps.invoke_semantic_supplement",
        return_value=stub,
    ):
        report = run_risk_analysis(req)
    assert int(report["risk_score"]) >= 25
    assert report["recommended_cai_action"] in ("ask_user", "block")
