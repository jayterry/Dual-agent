"""guard report → DAIResult / call_dai payload。"""

from __future__ import annotations

from typing import Any

from dual_agent.dai.schemas import DAIResult, DefenseObservation, DefensePlan


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
        "user_reason_highlights": list(report.get("user_reason_highlights") or []),
        "user_suggestions": list(report.get("user_suggestions") or []),
        "display_text": str(report.get("display_text") or ""),
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


def dai_result_from_sms_defense(
    plan: DefensePlan,
    report: dict[str, Any],
    observations: list[DefenseObservation],
    *,
    llm_turns: int = 1,
    error: str | None = None,
) -> DAIResult:
    """簡訊審查：Defense 計畫 + DAG 報告 → DAIResult。"""
    exec_ok = all(o.ok for o in observations) if observations else True
    risk_score = max(int(plan.risk_score), int(report.get("risk_score") or 0))
    safety = str(report.get("safety_summary") or plan.safety_summary or "").strip()
    if not safety:
        safety = "簡訊審查已完成。" if exec_ok else "簡訊審查執行未完成。"
    labels = list(report.get("labels") or plan.risk_labels or [])
    evidence = list(report.get("evidence") or plan.evidence or [])
    action = str(report.get("recommended_cai_action") or plan.recommended_cai_action or "continue")
    return DAIResult(
        ok=exec_ok and not error,
        risk_score=risk_score,
        risk_labels=labels,
        safety_summary=safety,
        evidence=evidence,
        tool_restrictions=dict(plan.tool_restrictions),
        recommended_cai_action=action,  # type: ignore[arg-type]
        defense_observations=list(observations),
        defense_llm_turns=llm_turns,
        error=error,
    )


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
