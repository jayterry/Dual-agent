"""DAI user_db：信任網域與 UEBA。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dual_agent.dai.user_db import (
    apply_ueba_to_report,
    compute_user_risk,
    enrich_dai_payload_with_ueba,
    list_trusted_domains,
    mark_trusted_domain,
    normalize_domain,
    remove_trusted_domain,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_user_db.json")


def test_normalize_domain() -> None:
    assert normalize_domain("https://www.Example.com/path") == "example.com"
    assert normalize_domain("bank.com.tw") == "bank.com.tw"


def test_trusted_domain_crud(db_path: str) -> None:
    mark_trusted_domain(domain="safe.example.com", path=db_path)
    assert "safe.example.com" in list_trusted_domains(path=db_path)
    remove_trusted_domain(domain="safe.example.com", path=db_path)
    assert "safe.example.com" not in list_trusted_domains(path=db_path)


def test_all_urls_trusted_lowers_delta_with_guardrail(db_path: str) -> None:
    from dual_agent.dai.user_db import record_seen

    mark_trusted_domain(domain="bank.com", path=db_path)
    record_seen(source="com.bank.app", path=db_path)
    record_seen(source="com.bank.app", path=db_path)
    text = "請點擊 https://bank.com/login 完成驗證"
    ur = compute_user_risk(
        text=text,
        source="com.bank.app",
        llm_verdict="allow",
        risk_total_fused=50,
        path=db_path,
    )
    assert ur.all_urls_trusted is True
    assert any("all_urls_trusted" in r for r in ur.reasons)
    assert any("all_urls_trusted" in r for r in ur.reasons)

    ur_high = compute_user_risk(
        text="https://bank.com/login",
        source="com.bank.app",
        llm_verdict="block",
        risk_total_fused=90,
        path=db_path,
    )
    assert ur_high.delta_user >= 0
    assert not ur_high.need_user_confirm


def test_enrich_dai_payload_adds_risk_user(db_path: str) -> None:
    mark_trusted_domain(domain="shop.test", path=db_path)
    payload = enrich_dai_payload_with_ueba(
        {"risk_score": 40, "safety_summary": "test"},
        text="訪問 https://shop.test/deal",
        source="sms",
        path=db_path,
    )
    assert "risk_user" in payload
    assert payload["risk_user"]["all_urls_trusted"] is True


def test_apply_ueba_to_report_dict(db_path: str) -> None:
    report = {
        "verdict": "allow",
        "risk_score_total": 55,
        "risk_score_total_fused": 55,
        "risk_fusion": {"risk_total": 55},
    }
    apply_ueba_to_report(
        report,
        text="https://unknown.evil/phish",
        source="unknown",
        path=db_path,
    )
    assert "risk_user" in report
    assert report["risk_score_total_user_fused"] is not None
