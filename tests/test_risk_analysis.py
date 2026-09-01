"""DAI risk_analysis：規則／威脅單元 + 雙路主路徑。"""

from __future__ import annotations

import os

from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.providers import score_r_threat_intel, score_r_tls
from dual_agent.dai.risk_analysis.rules import score_r_rules
from dual_agent.dai.risk_analysis.semantic_llm import invoke_semantic_supplement
from dual_agent.dai.schemas import DAIRequest


def _dual_off() -> None:
    os.environ["DAI_DUAL_PATH_B"] = "0"
    os.environ["DAI_DUAL_NARRATOR"] = "0"


def test_rules_password_high_score() -> None:
    res = score_r_rules("請立即驗證您的網路銀行密碼並回傳")
    assert res.score == 90
    assert any(h.rule_id == "password_credentials" for h in res.hits)


def test_dual_path_password_has_path_a() -> None:
    _dual_off()
    text = "請立即驗證您的網路銀行密碼並回傳"
    report = run_risk_analysis(
        DAIRequest(user_text=text, artifact=text, sms_review=True),
    )
    assert report.get("engine") == "fraud_dual"
    assert report.get("path_a")
    assert int(report["risk_score"]) >= 20
    assert "display_text" in report


def test_threat_intel_phishing_unit() -> None:
    hits = [
        {
            "url": "http://evil.test/x",
            "hits": {
                "virustotal": True,
                "phishtank": True,
                "urlhaus": True,
                "taiwan_165": True,
                "telco_blocklist": True,
            },
            "vendor_count": 5,
            "label": "phishing",
        }
    ]
    score, _ = score_r_threat_intel(hits)
    assert score == 40


def test_tls_empty_is_zero() -> None:
    score, _ = score_r_tls([])
    assert score == 0


def test_urgency_only_low_semantic_score() -> None:
    sem = invoke_semantic_supplement(
        payload={"text": "請立即處理"},
        component_scores={
            "r_rules": 0,
            "r_threat_intel": 0,
            "r_tls": 0,
            "r_toxic_fused": 0,
        },
        missing_evidence=[],
        machine_tier12_hit=False,
        enabled=False,
    )
    assert sem["r_llm_optional"] == 0


def test_llm_weight_35_when_machine_low() -> None:
    from dual_agent.dai.risk_analysis.verdict import (
        fuse_risk_score_weighted,
        scale_llm_score_to_100,
    )

    llm100 = scale_llm_score_to_100(20, tier_h=10, tier_i=5)
    fusion = fuse_risk_score_weighted(
        r_rules=0,
        r_threat_intel=0,
        r_tls=0,
        r_toxic_fused=0,
        r_llm_optional=20,
        tier_h=10,
        tier_i=5,
        llm_weight=0.35,
    )
    assert fusion.machine.r_machine_final == 0
    assert fusion.r_llm_100 == llm100
    assert fusion.r_fused == round(0.65 * 0 + 0.35 * llm100)


def test_dual_path_account_abnormal_url() -> None:
    _dual_off()
    report = run_risk_analysis(
        DAIRequest(
            user_text="帳戶異常請立即驗證 https://evil.test/x",
            artifact="帳戶異常請立即驗證 https://evil.test/x",
            sms_review=True,
        ),
    )
    assert report.get("engine") == "fraud_dual"
    assert isinstance(report.get("path_a"), dict)
    assert int(report["risk_score"]) >= 30
