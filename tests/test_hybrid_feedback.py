"""Hybrid feedback 與 pipeline thinking 測試。"""

from __future__ import annotations

from dual_agent.cai.hybrid.feedback import (
    append_observation,
    build_thinking_entries,
    finalize_turn_trace,
    init_turn_trace,
    record_message_features,
)
from dual_agent.cai.hybrid.schemas import ContentFeatures, MessageFeatures, TurnIntent
from dual_agent.cai.pipeline_progress import get_pipeline_status, init_pipeline_run, set_pipeline_stage
from dual_agent.skill_types import SkillContext


def test_turn_trace_and_thinking_entries() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "chat")
    init_turn_trace(ctx)
    features = MessageFeatures(
        turn_intent=TurnIntent(primary_goal="review_sms", intent_rationale_zh="有正文"),
        content=ContentFeatures(has_reviewable_body=True, artifact_text="test body"),
    )
    record_message_features(ctx, features)
    ctx.policy_state["message_features"] = features.model_dump()
    ctx.policy_state["react_trace"] = [{"thought": "送審", "action": {"type": "tool", "skill": "call_dai"}}]
    append_observation(ctx, "call_dai ok")
    finalize_turn_trace(ctx, final_answer="完成")
    entries = build_thinking_entries(ctx)
    kinds = [e["kind"] for e in entries]
    assert "nlp" in kinds
    assert "react" in kinds
    assert "finish" in kinds


def test_pipeline_status_includes_thinking() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "chat")
    set_pipeline_stage(ctx, flow="chat", stage="message_features")
    ctx.policy_state["message_features"] = {
        "turn_intent": {"primary_goal": "ask_missing_body"},
        "gaps": {"missing_body_for_review": True},
    }
    status = get_pipeline_status(ctx)
    assert "thinking" in status
    assert isinstance(status["thinking"]["entries"], list)
    assert status["thinking"]["entries"]
