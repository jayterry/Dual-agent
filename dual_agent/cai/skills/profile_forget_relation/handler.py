from __future__ import annotations

from typing import Any

from dual_agent.cai.profile_store import clear_relation, known_relations, resolve_profile_user_id
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relation_label": {"type": "string"},
    },
    "required": ["relation_label"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    label = str(args.get("relation_label") or "").strip()
    if not label:
        return SkillResult(ok=False, skill="profile_forget_relation", summary="缺少 relation_label", error="missing_args")
    uid = resolve_profile_user_id(ctx)
    clear_relation(label, user_id=uid)
    uf = ctx.policy_state.get("user_facts")
    if isinstance(uf, dict) and isinstance(uf.get("relations"), dict):
        uf["relations"].pop(label, None)
    sync = known_relations(uid)
    summary = f"已清除「{label}」的姓名記錄。"
    return SkillResult(ok=True, skill="profile_forget_relation", summary=summary, data={"relation_label": label, "relations": sync})
