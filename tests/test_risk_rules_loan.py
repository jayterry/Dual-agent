"""貸款／健保卡借款簡訊硬規則。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.summary import coherent_safety_summary
from dual_agent.dai.risk_analysis.rules import score_r_rules
from dual_agent.dai.risk_analysis.verdict import recommended_cai_action, verdict_from_score
from dual_agent.dai.schemas import DAIRequest


_LOAN_SMS = (
    "【健保卡借款】以月計息，放款迅速，無需擔保品，"
    "代償高利、免聯徵照會絕對保密，電洽：0979300280 林雅芳"
)


def test_loan_scam_rules_hit() -> None:
    res = score_r_rules(_LOAN_SMS)
    assert res.score >= 25
    rule_ids = {h.rule_id for h in res.hits}
    assert "loan_scam" in rule_ids or "nh_card_loan" in rule_ids or "unsolicited_loan_pitch" in rule_ids


def test_loan_scam_recommended_action_not_continue_only() -> None:
    req = DAIRequest(user_text="送審", artifact=_LOAN_SMS, sms_review=True)
    semantic_stub = {
        "r_llm_optional": 2,
        "tier_h": 0,
        "tier_i": 0,
        "explanation": "",
        "safety_summary": "此訊息存在較高的詐騙風險。",
        "labels": [],
        "skipped": False,
    }
    with patch(
        "dual_agent.dai.skills._pipeline_steps.invoke_semantic_supplement",
        return_value=semantic_stub,
    ):
        report = run_risk_analysis(req)
    score = int(report.get("risk_score") or 0)
    comps = report.get("component_scores") or {}
    r_rules = int(comps.get("r_rules") or 0)
    assert r_rules >= 25
    verdict = str(report.get("verdict") or verdict_from_score(score))
    action = recommended_cai_action(verdict, score, r_rules=r_rules)
    assert action == "ask_user"
    assert score >= 20


def test_coherent_summary_downgrades_mismatch() -> None:
    s = coherent_safety_summary(
        semantic_summary="此訊息存在較高的詐騙風險，請立即刪除。",
        risk_score=4,
        verdict="allow",
        r_rules=0,
    )
    assert "較高的詐騙風險" not in s
    assert "4/100" in s
