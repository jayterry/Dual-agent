from __future__ import annotations

from typing import Any

from dual_agent.cai.profile_store import known_relations, resolve_profile_user_id
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relation_label": {"type": "string"},
    },
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    label = str(args.get("relation_label") or "").strip()
    uid = resolve_profile_user_id(ctx)
    rels = known_relations(uid)
    if label:
        names = rels.get(label) or []
        if names:
            summary = f"{label}：" + "、".join(names)
        else:
            summary = f"尚未記錄{label}的姓名。"
    else:
        parts = [f"{k}：" + "、".join(v) for k, v in rels.items() if v]
        summary = "；".join(parts) if parts else "尚未記錄任何關係人姓名。"
    return SkillResult(ok=True, skill="profile_recall_relation", summary=summary, data={"relations": rels})
