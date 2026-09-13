"""quick_reply 確定性模板、短路與 few-shot loader。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.hybrid.message_features import _fallback_features, _format_fewshots
from dual_agent.cai.hybrid.prompts import load_fewshots
from dual_agent.cai.hybrid.quick_reply import try_quick_reply_shortcut
from dual_agent.cai.hybrid.schemas import (
    CapabilityFeatures,
    ContentFeatures,
    GapFeatures,
    MessageFeatures,
    TurnIntent,
)
from dual_agent.cai.hybrid.validate import validate_planner_from_features
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.pipeline_progress import _GOAL_THINKING, _SKILL_LABELS
from dual_agent.cai.schemas import PlanStep
from dual_agent.cai.skills.quick_reply.handler import (
    KIND_CAPABILITY,
    KIND_GREET,
    KIND_IDENTITY_ASSISTANT,
    KIND_IDENTITY_USER,
    KIND_OUT_OF_SCOPE,
    KIND_THANKS,
    display_name_from_ctx,
    handle,
    render_reply,
    resolve_kind,
)
from dual_agent.skill_types import SkillContext


def _features(
    goal: str,
    tags: list[str],
    *,
    oos: bool = False,
    has_body: bool = False,
) -> MessageFeatures:
    return MessageFeatures(
        turn_intent=TurnIntent(primary_goal=goal, confidence=0.95, intent_rationale_zh="測試"),
        content=ContentFeatures(
            has_reviewable_body=has_body,
            artifact_text="【銀行】點擊連結" if has_body else None,
        ),
        gaps=GapFeatures(out_of_product_scope=oos),
        capabilities=CapabilityFeatures(
            required_types=["direct_response"],
            domain_tags=list(tags),
            suggested_skills=["quick_reply"],
        ),
    )


def test_templates_six_kinds_and_display_name() -> None:
    greet_named = render_reply(KIND_GREET, display_name="Alex")
    greet_anon = render_reply(KIND_GREET, display_name="")
    assert "Alex" in greet_named
    assert "防詐助理" in greet_named
    assert "Alex" not in greet_anon
    assert "個人資料" in greet_anon

    who_bot = render_reply(KIND_IDENTITY_ASSISTANT, display_name="Alex")
    who_user_named = render_reply(KIND_IDENTITY_USER, display_name="Alex")
    who_user_anon = render_reply(KIND_IDENTITY_USER, display_name="")
    assert "防詐助理" in who_bot
    assert "您是" not in who_bot
    assert who_user_named == "您是 Alex。"
    assert "防詐助理" not in who_user_named
    assert "稱呼" in who_user_anon
    assert "Alex" not in who_user_anon

    thanks = render_reply(KIND_THANKS)
    cap = render_reply(KIND_CAPABILITY)
    oos = render_reply(KIND_OUT_OF_SCOPE)
    assert "不客氣" in thanks
    assert "審查" in cap and "還沒提供" in cap
    assert "還沒提供" in oos and "簡訊" in oos


def test_resolve_kind_priority_and_fallback() -> None:
    mixed = _features("assistant_chat", ["greet", "identity_assistant"])
    assert resolve_kind({}, mixed) == KIND_IDENTITY_ASSISTANT
    assert resolve_kind({"kind": "thanks"}, mixed) == KIND_THANKS
    assert resolve_kind({}, _features("out_of_scope", [])) == KIND_OUT_OF_SCOPE
    assert resolve_kind({}, _features("assistant_chat", [])) == KIND_GREET


def test_handle_reads_display_name_from_profile() -> None:
    ctx = SkillContext(user_input="您好")
    ctx.policy_state["user_profile"] = {"display_name": "Yuri"}
    ctx.policy_state["message_features"] = _features("assistant_chat", ["greet"]).model_dump()
    result = handle({}, ctx)
    assert result.ok
    assert result.skill == "quick_reply"
    assert result.data["kind"] == KIND_GREET
    assert "Yuri" in result.summary
    assert display_name_from_ctx(ctx) == "Yuri"


def test_shortcut_skips_when_reviewable_body_or_dai() -> None:
    ctx = SkillContext(user_input="")
    with_body = _features("assistant_chat", ["greet"], has_body=True)
    assert try_quick_reply_shortcut(with_body, ctx=ctx) is None
    oos = _features("out_of_scope", ["out_of_scope"], oos=True)
    assert try_quick_reply_shortcut(oos, ctx=ctx, requires_dai=True) is None
    review = _features("review_sms", ["safety_review"])
    assert try_quick_reply_shortcut(review, ctx=ctx) is None


def test_plan_execute_greet_shortcut_skips_planner() -> None:
    ctx = SkillContext(user_input="您好")
    ctx.policy_state["user_profile"] = {"display_name": "Alex"}
    planner = MagicMock()
    features = _features("assistant_chat", ["greet"])
    with patch("dual_agent.cai.plan_execute.hybrid_enabled", return_value=True):
        with patch("dual_agent.cai.plan_execute.invoke_message_features", return_value=features):
            with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
                out = run_plan_and_execute(user_text="您好", ctx=ctx)
    planner.assert_not_called()
    assert out.task_type == "direct_response"
    assert out.task_state == "completed"
    assert out.plan[0].skill == "quick_reply"
    assert "Alex" in out.answer
    assert "防詐助理" in out.answer


def test_plan_execute_weather_out_of_scope_guides_review() -> None:
    ctx = SkillContext(user_input="明天台北會下雨嗎")
    planner = MagicMock()
    features = _features("out_of_scope", ["out_of_scope"], oos=True)
    with patch("dual_agent.cai.plan_execute.hybrid_enabled", return_value=True):
        with patch("dual_agent.cai.plan_execute.invoke_message_features", return_value=features):
            with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
                out = run_plan_and_execute(user_text="明天台北會下雨嗎", ctx=ctx)
    planner.assert_not_called()
    assert out.task_type == "direct_response"
    assert out.plan[0].skill == "quick_reply"
    assert "還沒提供" in out.answer
    assert "簡訊" in out.answer


def test_nlp_fallback_uses_quick_reply_out_of_scope() -> None:
    ctx = SkillContext(user_input="???")
    planner = MagicMock()
    features = _fallback_features("???")
    assert features.primary_goal == "out_of_scope"
    with patch("dual_agent.cai.plan_execute.hybrid_enabled", return_value=True):
        with patch("dual_agent.cai.plan_execute.invoke_message_features", return_value=features):
            with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
                out = run_plan_and_execute(user_text="???", ctx=ctx)
    planner.assert_not_called()
    assert out.plan[0].args.get("kind") == KIND_OUT_OF_SCOPE
    assert "還沒提供" in out.answer


def test_validate_replaces_illegal_todos_with_quick_reply() -> None:
    features = _features("assistant_chat", ["capability"])
    todos, tt, ts, _msg = validate_planner_from_features(
        features,
        task_type="action",
        task_state="running",
        todos=[PlanStep(skill="call_dai", args={})],
        message="",
    )
    assert len(todos) == 1
    assert todos[0].skill == "quick_reply"
    assert todos[0].args.get("kind") == KIND_CAPABILITY
    assert tt == "direct_response"
    assert ts == "completed"


def test_fewshots_loader_includes_chat_examples() -> None:
    data = load_fewshots("message_features.json")
    ids = {str(e.get("id") or "") for e in (data.get("examples") or [])}
    assert {
        "fs_greet",
        "fs_thanks",
        "fs_capability",
        "fs_identity_assistant",
        "fs_identity_user",
        "fs_weather_oos",
        "fs_out_scope",
    } <= ids
    greet = next(e for e in data["examples"] if e["id"] == "fs_greet")
    assert greet["output"]["turn_intent"]["primary_goal"] == "assistant_chat"
    assert greet["output"]["capabilities"]["suggested_skills"] == ["quick_reply"]
    oos = next(e for e in data["examples"] if e["id"] == "fs_out_scope")
    assert oos["output"]["capabilities"]["suggested_skills"] == ["quick_reply"]
    blob = _format_fewshots()
    for needed in ("fs_greet", "fs_identity_assistant", "fs_out_scope", "fs_capability"):
        assert needed in blob


def test_pipeline_labels() -> None:
    assert _SKILL_LABELS["quick_reply"] == "快速回覆"
    assert "問候" in _GOAL_THINKING["assistant_chat"]
    assert "超出" in _GOAL_THINKING["out_of_scope"]
