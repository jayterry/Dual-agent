"""pending_review 放棄待審：偵測與管線整合（沙盒回歸）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.review_entry_eligibility import (
    looks_like_location_for_weather,
    looks_like_review_declined,
    looks_like_short_affirmative_pivot,
    should_abandon_pending_review,
)
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext


def test_looks_like_review_declined() -> None:
    assert looks_like_review_declined("我沒有要你看簡訊")
    assert looks_like_review_declined("不用再問簡訊了")
    assert not looks_like_review_declined("我收到一則簡訊")


def test_looks_like_short_affirmative_and_location() -> None:
    assert looks_like_short_affirmative_pivot("可以")
    assert looks_like_location_for_weather("台中市")
    assert not looks_like_location_for_weather("台灣台中市明天的天氣")


def test_should_abandon_requires_pending_context() -> None:
    assert not should_abandon_pending_review("我沒有要你看簡訊", pending_review=False)
    assert should_abandon_pending_review("我沒有要你看簡訊", pending_review=True)


def test_validate_decline_under_pending_review() -> None:
    todos, tt, _, _ = validate_planner_output(
        user_text="我沒有要你看簡訊",
        task_type="action",
        task_state="running",
        todos=[
            PlanStep(
                skill="ask_user",
                args={
                    "question": "請貼上完整簡訊或訊息內容，我才能幫您審查風險。",
                    "expected_task": "check",
                },
            )
        ],
        message="",
        pending_review=True,
    )
    assert tt == "direct_response"
    assert not todos


def test_plan_execute_clears_pending_review_on_decline() -> None:
    ctx = SkillContext(user_input="")
    planner = PlannerOutput(
        task_type="action",
        task_state="running",
        todos=[PlanStep(skill="weather", args={"location": "台中"})],
        message="",
    )
    replan = ReplanOutput(complete=True, final_answer="好的。", updated_todos=[], task_state="completed")

    def planner_fn(**_kwargs):
        return planner

    def replan_fn(**_kwargs):
        return replan

    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=planner_fn):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=replan_fn):
                run_plan_and_execute(user_text="我收到一則簡訊", ctx=ctx)
                assert ctx.policy_state.get("pending_review")
                run_plan_and_execute(user_text="我沒有要你看簡訊", ctx=ctx)
                assert not ctx.policy_state.get("pending_review")
