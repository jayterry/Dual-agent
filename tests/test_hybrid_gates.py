"""Hybrid MVP 技能白名單。"""

from __future__ import annotations

from dual_agent.cai.hybrid.gates import (
    MVP_SKILLS,
    allowed_skills_for,
    filter_tool_catalog,
    skill_allowed,
)
from dual_agent.cai.hybrid.schemas import MessageFeatures, TurnIntent


def test_quick_reply_in_mvp_whitelist() -> None:
    assert "quick_reply" in MVP_SKILLS


def test_assistant_chat_allows_quick_reply_not_dai() -> None:
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="assistant_chat"))
    allowed = set(allowed_skills_for(features))
    assert allowed == {"quick_reply", "confirm"}
    assert skill_allowed(features, "quick_reply")
    assert skill_allowed(features, "confirm")
    assert not skill_allowed(features, "call_dai")
    assert not skill_allowed(features, "search_web")


def test_out_of_scope_allows_quick_reply_not_dai() -> None:
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="out_of_scope"))
    allowed = set(allowed_skills_for(features))
    assert allowed == {"quick_reply", "confirm"}
    assert skill_allowed(features, "quick_reply")
    assert not skill_allowed(features, "call_dai")


def test_review_sms_still_allows_call_dai() -> None:
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="review_sms"))
    assert skill_allowed(features, "call_dai")
    assert not skill_allowed(features, "quick_reply")


def test_filter_tool_catalog_assistant_chat() -> None:
    catalog = [
        {"name": "quick_reply"},
        {"name": "call_dai"},
        {"name": "confirm"},
    ]
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="assistant_chat"))
    names = {e["name"] for e in filter_tool_catalog(catalog, features)}
    assert names == {"quick_reply", "confirm"}
