from __future__ import annotations

from typing import Any

from dual_agent.cai.profile_store import (
    clear_relation,
    resolve_profile_user_id,
    sync_relations_from_user_facts,
    upsert_relation,
)
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relation_label": {"type": "string"},
        "relation_name": {"type": "string"},
        "relation_category": {"type": "string"},
        "mode": {"type": "string", "enum": ["set", "append"]},
    },
    "required": ["relation_label", "relation_name"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    label = str(args.get("relation_label") or "").strip()
    name = str(args.get("relation_name") or "").strip()
    mode = str(args.get("mode") or "set").strip().lower()
    if not label or not name:
        return SkillResult(
            ok=False,
            skill="profile_remember_relation",
            summary="缺少 relation_label 或 relation_name",
            error="missing_args",
        )
    uid = resolve_profile_user_id(ctx)
    upsert_relation(label, name, mode=mode if mode in ("set", "append") else "set", user_id=uid)
    uf = ctx.policy_state.get("user_facts")
    if not isinstance(uf, dict):
        uf = {}
    rels = uf.setdefault("relations", {})
    if not isinstance(rels, dict):
        rels = {}
        uf["relations"] = rels
    bucket = rels.setdefault(label, [])
    if not isinstance(bucket, list):
        bucket = []
        rels[label] = bucket
    if mode == "append":
        if name not in bucket:
            bucket.append(name)
    else:
        rels[label] = [name]
    ctx.policy_state["user_facts"] = uf
    sync_relations_from_user_facts(uf, user_id=uid)
    summary = f"已記住：{label} → {name}"
    return SkillResult(ok=True, skill="profile_remember_relation", summary=summary, data={"relation_label": label, "relation_name": name})
