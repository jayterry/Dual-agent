"""recall_relation 確定性短路：查 Profile 模板回答。"""

from __future__ import annotations

from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.cai.profile_store import known_relations, resolve_profile_user_id
from dual_agent.cai.schemas import PlanExecuteOutcome, PlanStep
from dual_agent.skill_types import SkillContext


def try_recall_relation_shortcut(
    features: MessageFeatures,
    *,
    ctx: SkillContext,
) -> PlanExecuteOutcome | None:
    if features.primary_goal != "recall_relation":
        return None
    label = (features.social.relation_label or "").strip()
    if not label:
        return PlanExecuteOutcome(
            plan=[],
            results=[],
            answer="請告訴我您想回想哪位親友或朋友的稱謂，例如「媽媽」或「兒子」。",
            task_type="direct_response",
            task_state="completed",
        )
    uid = resolve_profile_user_id(ctx)
    rels = known_relations(uid)
    names = rels.get(label) or []
    if names:
        if len(names) == 1:
            answer = f"您的{label}是 {names[0]}。"
        else:
            joined = "、".join(names)
            answer = f"您的{label}是：{joined}。"
    else:
        answer = f"我還沒有記錄您的{label}姓名；您可以直接告訴我，例如「我{label}叫…」。"
    ctx.policy_state["last_message_features"] = features.model_dump()
    return PlanExecuteOutcome(
        plan=[PlanStep(skill="profile_recall_relation", args={"relation_label": label})],
        results=[],
        answer=answer,
        task_type="direct_response",
        task_state="completed",
    )
