"""送審結構化顯示：display_text、人話原因／建議、call_dai 完整 report。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.plan_execute import _format_answer_from_dai
from dual_agent.cai.skills.call_dai.handler import _extract_report_from_result
from dual_agent.dai.risk_analysis.review_display import (
    build_user_reasons,
    build_user_suggestions,
    enrich_report_display_fields,
    format_review_display,
)
from dual_agent.dai.schemas import DAIResult, DefenseObservation
from dual_agent.skill_types import SkillContext
from dual_agent.skills_registry import run_skill


_LOAN_SMS = (
    "【永豐貸】免擔保、月息 0.8%，額度 300 萬。加 LINE：abc123 私訊辦理。"
    "來源：com.instagram.android"
)


def test_build_user_reasons_loan_line() -> None:
    reasons = build_user_reasons(
        text=_LOAN_SMS,
        rules_hits=[{"rule_id": "loan_scam", "score": 25}],
        source="com.instagram.android",
    )
    joined = " ".join(reasons)
    assert any("貸款" in r or "借款" in r for r in reasons)
    assert "LINE" in joined or "line" in joined.lower()


def test_format_review_display_sections() -> None:
    text = format_review_display(
        risk_score=75,
        verdict="warn",
        reasons=["高額借款與低利率話術", "要求加入 LINE"],
        suggestions=["不要加入 LINE"],
    )
    assert "風險分數：75/100" in text
    assert "判定：warn" in text
    assert "主要原因：" in text
    assert "建議：" in text
    assert "• 高額借款" in text


def test_enrich_report_display_fields_warn_at_75() -> None:
    report = {
        "risk_score": 75,
        "verdict": "warn",
        "recommended_cai_action": "ask_user",
        "labels": ["suspicious_notification"],
        "track_a": {"matched_rules": [{"rule_id": "loan_scam", "score": 25}]},
        "component_scores": {"r_rules": 25, "r_threat_intel": 0, "r_tls": 0},
        "analysis_payload": {"urls": []},
    }
    enrich_report_display_fields(report, text=_LOAN_SMS, source="com.instagram.android")
    assert report["display_text"]
    assert "風險分數：75/100" in report["display_text"]
    assert "判定：warn" in report["display_text"]
    assert report["user_reason_highlights"]
    assert report["user_suggestions"]
    assert "75/100" in report["safety_summary"]
    assert "warn" in report["safety_summary"]
    assert "18/100" not in report["safety_summary"]


def test_extract_report_from_fuse_observation() -> None:
    full_report = {
        "risk_score": 75,
        "verdict": "warn",
        "component_scores": {"r_rules": 25},
        "display_text": "風險分數：75/100\n判定：warn",
        "user_reason_highlights": ["高額借款與低利率話術"],
    }
    out = DAIResult(
        ok=True,
        risk_score=75,
        risk_labels=[],
        safety_summary="",
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="ask_user",
        defense_observations=[
            DefenseObservation(
                skill="build_analysis_payload",
                ok=True,
                summary="build_analysis_payload ok",
                data={"step": "build_analysis_payload"},
            ),
            DefenseObservation(
                skill="fuse_risk_and_ueba",
                ok=True,
                summary="fuse ok",
                data={"step": "fuse_risk_and_ueba", "report": full_report},
            ),
        ],
    )
    got = _extract_report_from_result(out)
    assert got is not None
    assert got.get("display_text")
    assert "build_analysis_payload" not in str(got.get("user_reason_highlights"))


def _call_dai_handle():
    from dual_agent.skills_registry import SKILLS

    return SKILLS["call_dai"].handler


def test_call_dai_payload_uses_full_report_not_dag_steps() -> None:
    full_report = {
        "risk_score": 75,
        "verdict": "warn",
        "recommended_cai_action": "ask_user",
        "safety_summary": "綜合風險 75/100，判定 warn，請提高警覺並查證來源。",
        "component_scores": {"r_rules": 25},
        "reason_highlights": ["硬規則命中（25 分）"],
        "user_reason_highlights": ["高額借款與低利率話術", "要求加入 LINE"],
        "user_suggestions": ["不要加入 LINE"],
        "display_text": format_review_display(
            risk_score=75,
            verdict="warn",
            reasons=["高額借款與低利率話術", "要求加入 LINE"],
            suggestions=["不要加入 LINE"],
        ),
        "labels": [],
        "track_a": {},
        "analysis_payload": {},
    }
    fake = DAIResult(
        ok=True,
        risk_score=75,
        risk_labels=[],
        safety_summary=full_report["safety_summary"],
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="ask_user",
        defense_observations=[
            DefenseObservation(
                skill="build_analysis_payload",
                ok=True,
                summary="build_analysis_payload ok",
                data={"step": "build_analysis_payload"},
            ),
            DefenseObservation(
                skill="fuse_risk_and_ueba",
                ok=True,
                summary="fuse ok",
                data={"step": "fuse_risk_and_ueba", "report": full_report},
            ),
        ],
    )
    m = MagicMock(return_value=fake)
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill(
            "call_dai",
            {"artifact": _LOAN_SMS, "sms_review": True},
            SkillContext(user_input="送審"),
        )
    dai = r.data.get("dai") or {}
    assert dai.get("display_text")
    assert "判定：warn" in dai["display_text"]
    highlights = dai.get("reason_highlights") or []
    joined = " ".join(str(x) for x in highlights)
    assert "build_analysis_payload" not in joined
    assert "[DAI] 風險分數：75/100" in r.summary


def test_format_answer_from_dai_prefers_display_text() -> None:
    display = format_review_display(
        risk_score=75,
        verdict="warn",
        reasons=["測試原因"],
        suggestions=["測試建議"],
    )
    ans = _format_answer_from_dai({"display_text": display, "risk_score": 18})
    assert ans == display
    assert "18/100" not in ans
