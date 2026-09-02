"""Hybrid MVP：技能白名單與 allowed_skills gate。"""

from __future__ import annotations

from dual_agent.cai.hybrid.schemas import MessageFeatures

MVP_SKILLS: frozenset[str] = frozenset(
    {
        "call_dai",
        "ask_user",
        "profile_remember_relation",
        "profile_forget_relation",
        "profile_recall_relation",
        "confirm",
    }
)

_OUT_OF_SCOPE_SKILLS: frozenset[str] = frozenset()

_GOAL_ALLOWED: dict[str, frozenset[str]] = {
    "review_sms": frozenset({"call_dai", "ask_user", "confirm"}),
    "ask_missing_body": frozenset({"ask_user", "confirm"}),
    "follow_up_review": frozenset({"ask_user", "confirm"}),
    "remember_relation": frozenset({"profile_remember_relation", "ask_user", "confirm"}),
    "recall_relation": frozenset({"profile_recall_relation", "confirm"}),
    "out_of_scope": frozenset({"confirm"}),
}


def allowed_skills_for(features: MessageFeatures) -> list[str]:
    base = _GOAL_ALLOWED.get(features.primary_goal, frozenset({"ask_user", "confirm"}))
    return sorted(base & MVP_SKILLS)


def skill_allowed(features: MessageFeatures, skill: str) -> bool:
    name = (skill or "").strip().lower()
    if name not in MVP_SKILLS:
        return False
    return name in allowed_skills_for(features)


def filter_tool_catalog(catalog: list[dict], features: MessageFeatures | None) -> list[dict]:
    if features is None:
        allowed = MVP_SKILLS
    else:
        allowed = set(allowed_skills_for(features))
    out: list[dict] = []
    for entry in catalog:
        name = str(entry.get("name") or entry.get("skill") or "").strip().lower()
        if name in allowed:
            out.append(entry)
    return out
