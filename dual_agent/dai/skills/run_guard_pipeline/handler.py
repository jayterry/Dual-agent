from __future__ import annotations

import json
from typing import Any

from dual_agent.dai.guard_pipeline import run_guard_analysis_pipeline
from dual_agent.dai.schemas import DAIRequest
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "user_text": {"type": "string", "description": "使用者原句（若無 artifact 則用此跑管線）"},
        "artifact": {"type": "string", "description": "待審內容；非空時優先於 user_text"},
        "context_pack": {"type": "string", "description": "可選脈絡（寫入 DAIRequest）"},
        "source": {"type": "string", "description": "UEBA 來源標籤，預設 desktop"},
    },
    "required": [],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    user_text = str(args.get("user_text") or ctx.user_input or "").strip()
    artifact = str(args.get("artifact") or "").strip()
    context_pack = str(args.get("context_pack") or "").strip()
    source = str(args.get("source") or "desktop").strip() or "desktop"
    if not user_text and not artifact:
        return SkillResult(
            ok=False,
            skill="run_guard_pipeline",
            summary="需要 user_text 或 artifact",
            error="missing_input",
        )
    req = DAIRequest(user_text=user_text, artifact=artifact, context_pack=context_pack)
    try:
        report = run_guard_analysis_pipeline(req, source=source)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="run_guard_pipeline",
            summary=f"管線失敗：{e}",
            error=str(e),
        )
    ctx.guard_result = report
    slim = {
        "verdict": report.get("verdict"),
        "risk_score_total": report.get("risk_score_total"),
        "risk_score_total_user_fused": report.get("risk_score_total_user_fused"),
        "gate_tier": report.get("gate_tier"),
        "archive_note": report.get("archive_note"),
        "sanitized_memory": (str(report.get("sanitized_memory") or "")[:400]),
    }
    summary = json.dumps(slim, ensure_ascii=False)
    return SkillResult(
        ok=True,
        skill="run_guard_pipeline",
        summary=summary,
        data={"guard_report": report},
        evidence=[f"gate_tier={report.get('gate_tier')}"],
    )
