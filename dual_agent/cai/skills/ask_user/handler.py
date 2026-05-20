from __future__ import annotations

from typing import Any

from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "question": {"type": "string", "description": "要問使用者的問題"},
        "rationale": {"type": "string", "description": "為什麼需要這個資訊"},
    },
    "required": ["question"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    q = str(args.get("question") or "").strip()
    if not q:
        return SkillResult(ok=False, skill="ask_user", summary="缺少 question 參數", error="missing_question")
    rationale = str(args.get("rationale") or "").strip()
    expected_task = str(args.get("expected_task") or "").strip().lower() or None
    legacy = str(args.get("expected_intent") or "").strip().lower() or None
    if legacy == "external_message":
        legacy = "check"
    if expected_task is None and legacy:
        expected_task = legacy
    ctx.policy_state["pending_user_question"] = q
    ctx.policy_state["pending_task"] = {
        "type": "ask_user",
        "question": q,
        "rationale": rationale or None,
        "expected_task": expected_task,
    }
    if expected_task == "check":
        ing = ctx.policy_state.get("ingress_payload")
        origin = (
            str((ing or {}).get("input_origin") or "chat_box").strip()
            if isinstance(ing, dict)
            else "chat_box"
        )
        ctx.policy_state["pending_review"] = {
            "active": True,
            "source_turn": str(ctx.user_input or "").strip()[:2000],
            "input_origin": origin,
        }
    data = {"question": q}
    if rationale:
        data["rationale"] = rationale
    return SkillResult(ok=True, skill="ask_user", summary=q, data=data)

