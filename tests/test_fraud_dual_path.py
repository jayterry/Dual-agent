"""fraud_dual 硬取代主路徑（Path A 無需 Ollama）。"""

from __future__ import annotations

import os

from dual_agent.dai.pipeline_context import SMS_REVIEW_DAG
from dual_agent.dai.risk_analysis.dual_path import (
    channel_from_heuristics,
    persona_from_request,
    relation_from_heuristics,
    score01_to_100,
)
from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.schemas import DAIRequest


def _off_llm_env() -> dict[str, str | None]:
    keys = (
        "DAI_DUAL_PATH_B",
        "DAI_DUAL_NARRATOR",
        "DAI_DUAL_INFER_RELATION",
        "DAI_DUAL_INFER_CHANNEL",
    )
    prev = {k: os.environ.get(k) for k in keys}
    os.environ["DAI_DUAL_PATH_B"] = "0"
    os.environ["DAI_DUAL_NARRATOR"] = "0"
    os.environ["DAI_DUAL_INFER_RELATION"] = "0"
    os.environ["DAI_DUAL_INFER_CHANNEL"] = "0"
    return prev


def _restore_env(prev: dict[str, str | None]) -> None:
    for k, v in prev.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_sms_review_dag_is_dual_path_only() -> None:
    assert SMS_REVIEW_DAG == ("dual_path_analyze",)


def test_persona_defaults() -> None:
    p = persona_from_request(DAIRequest(user_text="x", source="sms"))
    assert p["age_band"] == "25-39"
    assert p["occupation"] == "other"
    assert p["relation_type"] == "Unknown"
    assert p["channel"] == "SMS"
    assert p["primary_apps"] == ["SMS"]


def test_otp_path_a_warn_or_block() -> None:
    prev = _off_llm_env()
    try:
        report = run_risk_analysis(
            DAIRequest(
                user_text="送審",
                artifact="【玉山銀行】帳戶異常，請回傳動態密碼 123456 完成驗證",
                sms_review=True,
                source="sms",
            )
        )
        assert report.get("engine") == "fraud_dual"
        assert report.get("path_a")
        assert int(report["risk_score"]) >= 55
        assert report["verdict"] in ("warn", "block")
        assert report["path_a"]["reasons"]
        assert report["path_a"]["warnings"]
        gate = max(
            int(report["path_a"]["threat_score_100"]),
            int(report["path_a"]["context_score_100"]),
        )
        assert int(report["risk_score"]) == gate
        assert "Path A" in (report.get("display_text") or "")
    finally:
        _restore_env(prev)


def test_score01_to_100() -> None:
    assert score01_to_100(0.7726) == 77
    assert score01_to_100(1.2) == 100
    assert score01_to_100(-1) == 0


def test_relation_heuristic_official() -> None:
    rel, conf, _ = relation_from_heuristics("【玉山銀行】帳戶異常，請回傳驗證碼")
    assert rel == "Official"
    assert conf >= 0.7


def test_otp_infers_official_relation() -> None:
    prev = _off_llm_env()
    try:
        report = run_risk_analysis(
            DAIRequest(
                user_text="送審",
                artifact="【玉山銀行】帳戶異常，請回傳動態密碼 123456 完成驗證",
                sms_review=True,
                source="sms",
            )
        )
        assert report.get("persona", {}).get("relation_type") == "Official"
        assert report.get("relation_inferred", {}).get("source") == "heuristic"
        assert report.get("persona", {}).get("channel") == "SMS"
        assert report.get("channel_inferred")
    finally:
        _restore_env(prev)


def test_channel_heuristic_line() -> None:
    ch, conf, _ = channel_from_heuristics(
        "請加入 LINE https://line.me/R/ti/p/@abc 查詢帳戶",
        source_fallback="SMS",
    )
    assert ch == "LINE"
    assert conf >= 0.7


def test_line_message_infers_channel() -> None:
    prev = _off_llm_env()
    try:
        report = run_risk_analysis(
            DAIRequest(
                user_text="送審",
                artifact="客服請加 LINE https://line.me/R/ti/p/@fakebank 完成驗證",
                sms_review=True,
                source="desktop",
                persona={"primary_apps": ["SMS", "LINE"]},
            )
        )
        assert report.get("persona", {}).get("channel") == "LINE"
        assert report.get("channel_inferred", {}).get("source") == "heuristic"
    finally:
        _restore_env(prev)
