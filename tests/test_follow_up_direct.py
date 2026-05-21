"""確定性追問／身份問答與 meta-only 宣告。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.follow_up_direct import (
    classify_follow_up_question,
    try_follow_up_direct_answer,
)
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.review_entry_eligibility import looks_like_declarative_sms_receipt_only
from dual_agent.cai.skills.call_dai.handler import artifact_is_meta_only_intent
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.schemas import PlanStep
from dual_agent.ingress import extract_entities, normalize_ingress
from dual_agent.skill_types import SkillContext


def test_creepy_message_receipt_is_meta_only() -> None:
    s = "我收到一個怪怪的訊息"
    ents = extract_entities(s)
    assert looks_like_declarative_sms_receipt_only(s, ents)
    assert artifact_is_meta_only_intent(s)


def test_classify_identity_questions() -> None:
    assert classify_follow_up_question("你是誰") == "assistant_identity"
    assert classify_follow_up_question("我是誰") == "user_identity"


def test_try_follow_up_assistant_identity() -> None:
    ans = try_follow_up_direct_answer("你是誰", context_pack="", user_profile={})
    assert ans
    assert "CAI" in ans
    assert ans != "你是誰"


def test_try_follow_up_user_identity_with_name() -> None:
    ans = try_follow_up_direct_answer(
        "我是誰",
        context_pack="",
        user_profile={"display_name": "ruby"},
    )
    assert ans
    assert "ruby" in ans
    assert "您是" in ans or "你叫" in ans


def test_run_plan_identity_skips_planner(monkeypatch) -> None:
    planner = MagicMock()
    replan = MagicMock()
    monkeypatch.setattr("dual_agent.cai.plan_execute.invoke_planner", planner)
    monkeypatch.setattr("dual_agent.cai.plan_execute.invoke_replan", replan)

    ctx = SkillContext(user_input="你是誰")
    ctx.policy_state["user_profile"] = {"display_name": "ruby"}

    out = run_plan_and_execute(user_text="你是誰", ctx=ctx, context_pack="")
    planner.assert_not_called()
    replan.assert_not_called()
    assert "CAI" in out.answer
    assert out.answer != "你是誰"


def test_run_plan_meta_receipt_asks_user_without_planner(monkeypatch) -> None:
    planner = MagicMock()
    replan = MagicMock()
    monkeypatch.setattr("dual_agent.cai.plan_execute.invoke_planner", planner)
    monkeypatch.setattr("dual_agent.cai.plan_execute.invoke_replan", replan)

    out = run_plan_and_execute(
        user_text="我收到一個怪怪的訊息",
        ctx=SkillContext(user_input="我收到一個怪怪的訊息"),
    )
    planner.assert_not_called()
    replan.assert_not_called()
    assert "貼上" in out.answer
    assert out.task_state == "waiting_input"


def test_planner_validate_meta_receipt_to_ask_user() -> None:
    step = PlanStep(skill="call_dai", args={"artifact": "我收到一個怪怪的訊息", "sms_review": True})
    todos, _, ts, _ = validate_planner_output(
        user_text="我收到一個怪怪的訊息",
        task_type="check",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert todos[0].skill == "ask_user"
    assert ts == "waiting_input"


def test_normalize_creepy_message_pending() -> None:
    ing = normalize_ingress(raw_input_text="我收到一個怪怪的訊息", input_origin="chat_box")
    assert ing.metadata.get("review_pending_candidate") is True
    assert ing.requires_dai is False
    assert not ing.artifact_text
