"""guard report → DAIResult / call_dai payload。"""

from __future__ import annotations

from typing import Any

from dual_agent.dai.schemas import DAIResult, DefenseObservation


def risk_report_to_dai_payload(report: dict[str, Any]) -> dict[str, Any]:
    risk_score = int(report.get("risk_score") or report.get("risk_score_total") or 0)
    verdict = str(report.get("verdict") or "allow")
    return {
        "ok": True,
        "risk_score": risk_score,
        "verdict": verdict,
        "dominant_source": str(report.get("dominant_source") or ""),
        "component_scores": dict(report.get("component_scores") or {}),
        "evidence": list(report.get("evidence") or []),
        "reason_highlights": list(report.get("reason_highlights") or []),
        "track_a": dict(report.get("track_a") or {}),
        "risk_labels": list(report.get("labels") or []),
        "safety_summary": str(report.get("safety_summary") or ""),
        "tool_restrictions": {},
        "recommended_cai_action": str(report.get("recommended_cai_action") or "continue"),
        "defense_llm_turns": 0 if report.get("semantic", {}).get("skipped") else 1,
        "defense_observations": [
            {
                "skill": "risk_analysis",
                "ok": True,
                "summary": str(report.get("archive_note") or "")[:800],
                "data": report,
            }
        ],
        "risk_user": report.get("risk_user"),
        "risk_score_user_fused": report.get("risk_score_total_user_fused"),
        "gate_tier": report.get("gate_tier"),
        "error": None,
    }


def dai_result_from_risk_report(report: dict[str, Any]) -> DAIResult:
    payload = risk_report_to_dai_payload(report)
    obs = DefenseObservation(
        skill="risk_analysis",
        ok=True,
        summary=str(report.get("safety_summary") or report.get("archive_note") or "")[:800],
        data=report,
    )
    return DAIResult(
        ok=True,
        risk_score=int(payload["risk_score"]),
        risk_labels=list(payload.get("risk_labels") or []),
        safety_summary=str(payload.get("safety_summary") or ""),
        evidence=list(payload.get("evidence") or []),
        tool_restrictions={},
        recommended_cai_action=payload.get("recommended_cai_action") or "continue",  # type: ignore[arg-type]
        defense_observations=[obs],
        defense_llm_turns=int(payload.get("defense_llm_turns") or 0),
        error=None,
    )
