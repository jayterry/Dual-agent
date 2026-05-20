"""DAI risk_analysis：機器層 max 合成 + 語意護欄。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.providers import score_r_threat_intel, score_r_tls
from dual_agent.dai.risk_analysis.rules import score_r_rules
from dual_agent.dai.risk_analysis.semantic_llm import invoke_semantic_supplement
from dual_agent.dai.schemas import DAIRequest


def test_rules_password_high_score() -> None:
    res = score_r_rules("請立即驗證您的網路銀行密碼並回傳")
    assert res.score == 25
    assert any(h.rule_id == "password_credentials" for h in res.hits)


def test_r_final_takes_max_rules_over_low_llm() -> None:
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "0"}, clear=False):
        report = run_risk_analysis(
            DAIRequest(user_text="請驗證網銀密碼", artifact="請驗證網銀密碼", sms_review=True),
        )
    cs = report["component_scores"]
    assert cs["r_rules"] == 25
    assert report["r_final_machine"] == max(
        cs["r_rules"],
        cs["r_threat_intel"],
        cs["r_tls"],
        cs["r_toxic_fused"],
        cs["r_llm_optional"],
    )
    assert report["risk_score"] >= 25


def test_threat_intel_phishing_dominates() -> None:
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
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "0"}, clear=False):
        report = run_risk_analysis(
            DAIRequest(user_text="點擊 http://evil.test/x", artifact="點擊 http://evil.test/x"),
            url_threat_hits_injected=hits,
        )
    assert report["component_scores"]["r_threat_intel"] == 40
    assert report["r_final_machine"] == 40


def test_missing_tls_zero_and_listed() -> None:
    score, _ = score_r_tls([])
    assert score == 0
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "0"}, clear=False):
        report = run_risk_analysis(
            DAIRequest(user_text="請點擊 https://example.com", artifact="https://example.com"),
            tls_findings_injected=[],
        )
    assert report["component_scores"]["r_tls"] == 0
    assert "tls_findings" in report["track_a"]["missing_evidence"]


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


@patch("dual_agent.dai.risk_analysis.pipeline.invoke_semantic_supplement")
def test_semantic_cannot_invent_threat_intel_score(mock_sem: object) -> None:
    mock_sem.return_value = {
        "r_llm_optional": 90,
        "tier_h": 20,
        "tier_i": 12,
        "explanation": "假裝惡意 URL",
        "safety_summary": "高風險",
        "labels": [],
        "quotes": [],
        "skipped": False,
    }
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "1"}, clear=False):
        report = run_risk_analysis(
            DAIRequest(user_text="你好", artifact="你好"),
            url_threat_hits_injected=[],
            tls_findings_injected=[],
        )
    # max() 仍不含捏造：機器全 0 時 r_final 應被 cap 在語意層 32 以內，且測試重點是 r_threat_intel=0
    assert report["component_scores"]["r_threat_intel"] == 0
    assert report["component_scores"]["r_tls"] == 0
    assert report["component_scores"]["r_llm_optional"] <= 32
    assert report["r_final_machine"] <= 32


def test_max_not_average() -> None:
    with patch.dict(os.environ, {"DAI_SEMANTIC_LLM": "0"}, clear=False):
        report = run_risk_analysis(
            DAIRequest(
                user_text="請驗證網銀密碼 http://evil.test",
                artifact="請驗證網銀密碼",
            ),
            url_threat_hits_injected=[
                {
                    "url": "http://evil.test",
                    "hits": {"virustotal": True, "phishtank": False, "urlhaus": False, "taiwan_165": False, "telco_blocklist": False},
                    "vendor_count": 1,
                    "label": "phishing",
                }
            ],
        )
    cs = report["component_scores"]
    expected = max(cs["r_rules"], cs["r_threat_intel"], cs["r_tls"], cs["r_toxic_fused"], cs["r_llm_optional"])
    assert report["r_final_machine"] == expected
    assert report["r_final_machine"] != int(
        round(
            (cs["r_rules"] + cs["r_threat_intel"] + cs["r_tls"] + cs["r_toxic_fused"] + cs["r_llm_optional"]) / 5
        )
    )
