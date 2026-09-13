"""assistant_chat / out_of_scope 確定性短路：跑 quick_reply，不進 Planner。"""

from __future__ import annotations

from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.cai.schemas import PlanExecuteOutcome, PlanStep
from dual_agent.cai.skills.quick_reply.handler import handle, resolve_kind
from dual_agent.skill_types import SkillContext


def try_quick_reply_shortcut(
    features: MessageFeatures,
    *,
    ctx: SkillContext,
    requires_dai: bool = False,
) -> PlanExecuteOutcome | None:
    if features.primary_goal not in ("assistant_chat", "out_of_scope"):
        return None
    if requires_dai or bool(features.content.has_reviewable_body):
        return None
    kind = resolve_kind({}, features)
    result = handle({"kind": kind}, ctx)
    ctx.policy_state["last_message_features"] = features.model_dump()
    return PlanExecuteOutcome(
        plan=[PlanStep(skill="quick_reply", args={"kind": kind})],
        results=[result],
        answer=result.summary,
        task_type="direct_response",
        task_state="completed",
    )
