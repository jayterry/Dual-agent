"""工作紀錄與 pending_review 生命週期（插問保留、天氣不 abandon）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.context_layer import SessionMemory, record_turn, record_turn_after_review
from dual_agent.cai.hybrid.schemas import CapabilityFeatures, ContentFeatures, MessageFeatures, TurnIntent
from dual_agent.cai.plan_execute import (
    _apply_features_to_work_record,
    _set_pending_review,
    run_plan_and_execute,
)
from dual_agent.cai.review_entry_eligibility import should_abandon_pending_review
from dual_agent.cai.schemas import PlannerOutput, ReplanOutput
from dual_agent.cai.work_record import (
    format_work_record_for_prompt,
    is_work_open,
    on_aside,
    on_waiting_for_body,
    start_work,
)
from dual_agent.ingress import normalize_ingress
from dual_agent.skill_types import SkillContext


def test_should_abandon_only_on_explicit_decline() -> None:
    assert should_abandon_pending_review("我沒有要你看簡訊", pending_review=True)
    assert should_abandon_pending_review("不用了", pending_review=True, turn_relation="cancel")
    assert not should_abandon_pending_review("明天台北天氣", pending_review=True)
    assert not should_abandon_pending_review("台中市", pending_review=True)
    assert not should_abandon_pending_review("可以", pending_review=True)
    assert not should_abandon_pending_review("你好", pending_review=True)
    assert not should_abandon_pending_review(
        "我媽媽叫 Yuri", pending_review=True, turn_relation="clarify"
    )
    assert not should_abandon_pending_review("搜尋天氣再開連結", pending_review=True)


def test_work_record_waiting_and_aside_preserve_progress() -> None:
    snap = on_waiting_for_body({}, question="請貼上完整簡訊")
    assert snap["status"] == "waiting"
    assert snap["waiting_for"] == "reviewable_body"
    assert "work_id" in snap
    aside = on_aside(snap)
    assert aside["turn_relation"] == "aside"
    assert aside["status"] == "waiting"
    assert aside["waiting_for"] == "reviewable_body"
    assert aside["work_id"] == snap["work_id"]
    assert is_work_open(aside)


def test_start_work_resets_review_fields() -> None:
    old = on_waiting_for_body(
        {
            "artifact_excerpt": "舊簡訊",
            "last_risk_score": 90,
            "review_phase": "review_completed",
            "completed": ["call_dai"],
        },
        question="q",
    )
    new = start_work(keep_background={"task_type": "check", "display_hint": "keep"})
    assert new["work_id"] != old.get("work_id")
    assert "artifact_excerpt" not in new
    assert "last_risk_score" not in new
    assert new.get("completed") == []
    assert new.get("task_type") == "check"


def test_record_turn_preserves_work_fields() -> None:
    session = SessionMemory()
    session.task_snapshot = on_waiting_for_body({}, question="請貼正文")
    wid = session.task_snapshot["work_id"]
    record_turn(
        session,
        user="你好",
        assistant="您好",
        task_type="direct_response",
        task_state="completed",
        model="x",
        base_url="http://127.0.0.1",
    )
    assert session.task_snapshot["work_id"] == wid
    assert session.task_snapshot["waiting_for"] == "reviewable_body"
    assert session.task_snapshot["task_type"] == "direct_response"


def test_record_turn_after_review_marks_completed() -> None:
    session = SessionMemory()
    session.task_snapshot = on_waiting_for_body({}, question="請貼正文")
    snap = record_turn_after_review(
        session,
        user="【銀行】點擊",
        assistant="風險高",
        task_type="check",
        task_state="completed",
        model="x",
        base_url="http://127.0.0.1",
        artifact="【銀行】點擊 http://x",
        dai={"risk_score": 88, "safety_summary": "疑似釣魚"},
    )
    assert snap["status"] == "completed"
    assert snap["review_phase"] == "review_completed"
    assert snap["last_risk_score"] == 88
    assert "call_dai" in snap["completed"]


def test_format_work_record_mentions_next_action_not_auth() -> None:
    txt = format_work_record_for_prompt(
        on_waiting_for_body({}, question="請貼上完整簡訊")
    )
    assert "等待" in txt or "waiting" in txt.lower() or "正文" in txt
    assert "非執行授權" in txt or "下一步" in txt


def test_apply_features_aside_keeps_pending() -> None:
    ctx = SkillContext(user_input="")
    ingress = normalize_ingress(raw_input_text="幫我看簡訊", input_origin="chat_box")
    _set_pending_review(ctx, ingress)
    assert ctx.policy_state.get("pending_review")
    features = MessageFeatures(
        turn_intent=TurnIntent(
            primary_goal="assistant_chat",
            turn_relation="aside",
            intent="greet",
            scope="in_scope",
        ),
        capabilities=CapabilityFeatures(suggested_skills=["quick_reply"], domain_tags=["greet"]),
    )
    hi = normalize_ingress(raw_input_text="你好", input_origin="chat_box")
    _apply_features_to_work_record(ctx, features, ingress=hi)
    assert ctx.policy_state.get("pending_review")
    snap = ctx.policy_state["task_snapshot"]
    assert snap["turn_relation"] == "aside"
    assert snap["status"] == "waiting"


def test_weather_during_pending_does_not_clear() -> None:
    ctx = SkillContext(user_input="")
    # Round 1: ask for body
    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.invoke_planner") as planner:
            out1 = run_plan_and_execute(user_text="我收到一則簡訊有點奇怪", ctx=ctx)
    planner.assert_not_called()
    assert ctx.policy_state.get("pending_review")
    snap1 = dict(ctx.policy_state.get("task_snapshot") or {})
    assert snap1.get("status") == "waiting"

    features = MessageFeatures(
        turn_intent=TurnIntent(
            primary_goal="out_of_scope",
            turn_relation="aside",
            intent="ask_weather",
            scope="out_of_scope",
            intent_rationale_zh="問天氣，插問",
        ),
        content=ContentFeatures(user_comment="明天天氣"),
        capabilities=CapabilityFeatures(
            required_types=["direct_response"],
            domain_tags=["out_of_scope"],
            suggested_skills=["quick_reply"],
        ),
    )
    planner2 = MagicMock()
    with patch("dual_agent.cai.plan_execute.hybrid_enabled", return_value=True):
        with patch("dual_agent.cai.plan_execute.invoke_message_features", return_value=features):
            with patch("dual_agent.cai.plan_execute.invoke_planner", planner2):
                out2 = run_plan_and_execute(user_text="明天台北會下雨嗎", ctx=ctx)
    planner2.assert_not_called()
    assert ctx.policy_state.get("pending_review"), "天氣插問不得取消待審"
    assert (ctx.policy_state.get("task_snapshot") or {}).get("status") == "waiting"
    assert out2.task_type == "direct_response"


def test_explicit_cancel_clears_pending() -> None:
    ctx = SkillContext(user_input="")
    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        run_plan_and_execute(user_text="我收到一則簡訊有點奇怪", ctx=ctx)
    assert ctx.policy_state.get("pending_review")

    def fake_planner(**_kwargs):
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="")

    def fake_replan(**_kwargs):
        return ReplanOutput(
            complete=True,
            final_answer="好的，已取消。",
            updated_todos=[],
            task_state="completed",
        )

    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_planner):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan):
                run_plan_and_execute(user_text="我沒有要你看簡訊", ctx=ctx)
    assert not ctx.policy_state.get("pending_review")
    assert (ctx.policy_state.get("task_snapshot") or {}).get("status") == "cancelled"
