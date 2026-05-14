from __future__ import annotations

from typing import Any

from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"action": {"type": "string", "enum": ["approve", "cancel"]}},
    "required": ["action"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    action = str(args.get("action") or "").strip().lower()
    pending = ctx.policy_state.get("pending_plan")
    if action not in ("approve", "cancel"):
        return SkillResult(ok=False, skill="confirm", summary="action 只允許 approve 或 cancel", error="invalid_action")
    if not pending:
        return SkillResult(ok=False, skill="confirm", summary="目前沒有待確認的計畫", error="no_pending_plan")

    if action == "cancel":
        ctx.policy_state.pop("pending_plan", None)
        return SkillResult(ok=True, skill="confirm", summary="已取消待確認的計畫")

    ctx.policy_state["confirmed"] = True
    return SkillResult(ok=True, skill="confirm", summary="已確認，將執行待確認的計畫")

