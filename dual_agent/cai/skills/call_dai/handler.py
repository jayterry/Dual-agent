from __future__ import annotations

import re
from typing import Any

from dual_agent.dai.invoke import invoke_dai
from dual_agent.dai.risk_analysis.reporting import risk_report_to_dai_payload
from dual_agent.dai.user_db import enrich_dai_payload_with_ueba
from dual_agent.dai.schemas import DAIRequest, DAIResult
from dual_agent.cai.review_entry_eligibility import artifact_meta_only_for_dai
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact": {
            "type": "string",
            "description": "待審全文（簡訊內容等）；優先於本輪輸入",
        },
        "user_text": {
            "type": "string",
            "description": "使用者說明（如「幫我看是否詐騙」）；可省略",
        },
        "context_pack": {"type": "string", "description": "可選長脈絡"},
        "sms_review": {
            "type": "boolean",
            "description": "預設 true：簡訊審查（Defense 先排 todos 再執行）",
        },
    },
    "required": [],
}


_PLACEHOLDER_ARTIFACTS: frozenset[str] = frozenset(
    {
        "我收到一則簡訊",
        "我收到簡訊",
        "收到一則簡訊",
        "我剛收到簡訊",
        "我剛收到一則簡訊",
        "收到簡訊",
        "有一則簡訊",
        "我有一則簡訊",
        "剛收到一則簡訊",
        "收到一封簡訊",
        "我收到一封簡訊",
    }
)


def _norm_artifact(s: str) -> str:
    t = "".join(str(s).split())
    return t.strip("。．.!！？").strip()


def artifact_is_meta_only_intent(artifact: str) -> bool:
    if artifact_meta_only_for_dai(artifact):
        return True
    t = _norm_artifact(artifact)
    if not t:
        return True
    if len(t) > 48:
        return False
    low = t.lower()
    if "http://" in low or "https://" in low:
        return False
    if re.search(r"\d{4,}", t):
        return False
    if t in _PLACEHOLDER_ARTIFACTS:
        return True
    if len(t) <= 22:
        meta_patterns = (
            r"^幫我(看一下|看看)?(這)?則?簡訊$",
            r"^(請)?幫我審(一下)?(這)?則?簡訊$",
            r"^審(一下)?(這)?則?簡訊$",
            r"^幫我看是不是詐騙簡訊$",
        )
        for pat in meta_patterns:
            if re.match(pat, t):
                return True
    return False


def _boolish(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("false", "0", "no", "off"):
        return False
    if s in ("true", "1", "yes", "on"):
        return True
    return default


def _extract_report_from_result(out: DAIResult) -> dict[str, Any] | None:
    """從 defense_observations 取出完整 DAG report（含 display_text）。"""
    best: dict[str, Any] | None = None
    for obs in out.defense_observations:
        data = obs.data if hasattr(obs, "data") else {}
        if not isinstance(data, dict):
            continue
        nested = data.get("report")
        if isinstance(nested, dict) and nested.get("component_scores"):
            best = nested
            continue
        if data.get("component_scores"):
            best = data
    return best


def _dai_payload_from_report(report: dict[str, Any], out: DAIResult) -> dict[str, Any]:
    payload = risk_report_to_dai_payload(report)
    payload["ok"] = out.ok
    payload["error"] = out.error
    payload["defense_llm_turns"] = out.defense_llm_turns
    return payload


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    ctx_in = (ctx.user_input or "").strip()
    artifact = str(args.get("artifact") or "").strip()
    user_text = str(args.get("user_text") or "").strip()
    context_pack = str(args.get("context_pack") or "").strip()
    if not context_pack:
        context_pack = str(ctx.policy_state.get("context_pack") or "").strip()
    sms_review = _boolish(args.get("sms_review"), True)

    if not artifact:
        artifact = ctx_in
    if not user_text:
        user_text = ctx_in or "請審查下列內容"

    if not artifact.strip():
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary="缺少待審內容：請在 artifact 提供簡訊全文，或於對話中貼上內文",
            error="missing_artifact",
        )

    if artifact_is_meta_only_intent(artifact):
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary="尚未取得可審查的簡訊正文：請貼上完整簡訊內容（勿只送出「收到簡訊」等說明句）。",
            error="artifact_meta_only",
        )

    review_source = str(ctx.policy_state.get("review_source") or "").strip()
    req = DAIRequest(
        user_text=user_text,
        artifact=artifact,
        context_pack=context_pack,
        sms_review=sms_review,
        source=review_source or "desktop",
    )
    try:
        out = invoke_dai(req, pipeline_ctx=ctx)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary=f"DAI 呼叫失敗：{e}",
            error=str(e),
        )

    if out.ok:
        ctx.policy_state.pop("pending_review", None)

    report = _extract_report_from_result(out)
    if report:
        payload = _dai_payload_from_report(report, out)
    else:
        payload = {
            "ok": out.ok,
            "risk_score": out.risk_score,
            "verdict": "allow",
            "safety_summary": out.safety_summary,
            "recommended_cai_action": out.recommended_cai_action,
            "reason_highlights": [],
            "user_reason_highlights": [],
            "user_suggestions": [],
            "display_text": "",
            "error": out.error,
        }

    if not payload.get("risk_user"):
        payload = enrich_dai_payload_with_ueba(
            payload, text=artifact, source=review_source or None
        )

    display = str(payload.get("display_text") or "").strip()
    if display:
        summary = f"[DAI] {display.splitlines()[0]}"
    else:
        summary = f"[DAI] 風險分數 {out.risk_score}/100"

    return SkillResult(
        ok=out.ok,
        skill="call_dai",
        summary=summary,
        data={"dai": payload, "risk_user": payload.get("risk_user")},
        evidence=[f"recommended_cai_action={payload.get('recommended_cai_action')}"],
    )
