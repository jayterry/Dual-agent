"""Hybrid feedback 與 pipeline thinking 測試。"""

from __future__ import annotations

from dual_agent.cai.hybrid.feedback import (
    append_observation,
    build_thinking_entries,
    finalize_turn_trace,
    init_turn_trace,
    record_message_features,
    record_planner_todos,
)
from dual_agent.cai.hybrid.schemas import ContentFeatures, MessageFeatures, TurnIntent
from dual_agent.cai.pipeline_progress import (
    append_infer_thinking,
    append_path_a_thinking,
    append_path_b_thinking,
    append_thinking,
    get_pipeline_status,
    init_pipeline_run,
    set_pipeline_stage,
)
from dual_agent.cai.schemas import PlanStep
from dual_agent.skill_types import SkillContext


def _thinking_len(ctx: SkillContext) -> int:
    return len(build_thinking_entries(ctx))


def _texts(ctx: SkillContext) -> list[str]:
    return [
        str((e.get("detail") or {}).get("text") or "")
        for e in build_thinking_entries(ctx)
        if isinstance(e, dict)
    ]


def test_turn_trace_and_thinking_entries() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "chat")
    init_turn_trace(ctx)
    assert _thinking_len(ctx) == 0
    assert all(e["kind"] != "finish" for e in build_thinking_entries(ctx))

    set_pipeline_stage(ctx, flow="chat", stage="ingress")
    set_pipeline_stage(ctx, flow="chat", stage="message_features")
    assert _thinking_len(ctx) == 0

    features = MessageFeatures(
        turn_intent=TurnIntent(primary_goal="review_sms", intent_rationale_zh="有正文和短網址"),
        content=ContentFeatures(has_reviewable_body=True, artifact_text="test body"),
    )
    record_message_features(ctx, features)
    ctx.policy_state["message_features"] = features.model_dump()
    nlp_texts = _texts(ctx)
    assert any(e["kind"] == "nlp" for e in build_thinking_entries(ctx))
    assert any("有正文和短網址" in t for t in nlp_texts)
    assert any("送審" in t for t in nlp_texts)

    record_planner_todos(ctx, [PlanStep(skill="call_dai", args={})], message="內文可審，交給風險分析。")
    assert any(e["kind"] == "planner" for e in build_thinking_entries(ctx))
    assert any("風險分析" in t for t in _texts(ctx))

    append_thinking(ctx, "react", "為什麼這樣做", "因為有可審正文，先送去風險分析。")
    ctx.policy_state["react_trace"] = [{"thought": "送審", "action": {"type": "tool", "skill": "call_dai"}}]
    append_observation(ctx, "call_dai ok")
    finalize_turn_trace(ctx, final_answer="完成")
    entries = build_thinking_entries(ctx)
    kinds = [e["kind"] for e in entries]
    assert "nlp" in kinds
    assert "react" in kinds
    assert "finish" not in kinds
    assert not any("完成" == e.get("label_zh") for e in entries)


def test_pipeline_status_includes_thinking() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "chat")
    set_pipeline_stage(ctx, flow="chat", stage="message_features")
    record_message_features(
        ctx,
        MessageFeatures(
            turn_intent=TurnIntent(primary_goal="ask_missing_body", intent_rationale_zh="只有『幫我看簡訊』沒有正文"),
        ),
    )
    status = get_pipeline_status(ctx)
    assert "thinking" in status
    assert isinstance(status["thinking"]["entries"], list)
    assert status["thinking"]["entries"]
    texts = [
        str((e.get("detail") or {}).get("text") or "")
        for e in status["thinking"]["entries"]
        if isinstance(e, dict)
    ]
    assert any("沒有正文" in t or "缺正文" in t for t in texts)
    assert not any("開始處理這則訊息" in t for t in texts)


def test_thinking_records_conclusions_not_stage_busy() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "review")
    set_pipeline_stage(ctx, flow="review", stage="dai")
    assert _thinking_len(ctx) == 0
    append_infer_thinking(
        ctx,
        channel_meta={"channel": "Telegram", "reason": "內文出現 t.me 連結"},
        relation_meta={"relation_type": "Unknown", "reason": "沒有自稱熟人"},
    )
    append_path_a_thinking(
        ctx,
        threat100=88,
        context100=41,
        scam_type="Fake_CS",
        clues=["限時要求", "短網址"],
        factors=["Telegram 非常用平台"],
    )
    append_path_b_thinking(
        ctx,
        explanation="語氣很催、又要下載 App，比較像假客服。",
        threat100=80,
        context100=55,
    )
    texts = _texts(ctx)
    assert any("t.me" in t and "Telegram" in t for t in texts)
    assert any("Unknown" in t and "熟人" in t for t in texts)
    assert any("限時要求" in t and "線索分" in t and "88/100" in t for t in texts)
    assert any("假客服" in t for t in texts)
    assert any("語氣很催" in t for t in texts)
    assert not any("80/100" in t or "它給的威脅" in t for t in texts)
    assert not any("正在推斷" in t or "開始跑技能" in t for t in texts)
    assert all(e.get("kind") != "finish" for e in build_thinking_entries(ctx))


def test_append_thinking_skips_adjacent_duplicate() -> None:
    ctx = SkillContext(user_input="測試")
    init_pipeline_run(ctx, "chat")
    assert _thinking_len(ctx) == 0
    append_thinking(ctx, "nlp", "理解意圖", "有正文。")
    n = _thinking_len(ctx)
    append_thinking(ctx, "nlp", "理解意圖", "有正文。")
    assert _thinking_len(ctx) == n
    append_thinking(ctx, "nlp", "理解意圖", "另一句。")
    assert _thinking_len(ctx) == n + 1
