"""task_snapshot、Planner 依工作狀態判斷（非追問硬路由）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.context_layer import (
    SessionMemory,
    format_work_state_summary,
    is_follow_up_on_completed_review,
    merge_user_profile,
    pack_context,
    record_turn_after_review,
    should_block_repeat_call_dai,
)
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext


def test_pack_context_work_state_summary() -> None:
    mem = SessionMemory()
    merge_user_profile(mem, {"display_name": "Terry"})
    record_turn_after_review(
        mem,
        user="審查",
        assistant="完成",
        task_type="check",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1",
        artifact="test body",
        message_source="sms:123",
        dai={"risk_score": 12},
    )
    packed = pack_context(mem)
    assert "【上一輪任務狀態】" in packed
    assert "review_completed" in packed
    assert "上次風險分數" in packed
    summ = format_work_state_summary(mem.task_snapshot)
    assert "review_completed" in summ


def test_should_block_repeat_call_dai() -> None:
    snap = {"review_phase": "review_completed", "artifact_key": "同一則簡訊正文"}
    assert should_block_repeat_call_dai(snap, artifact_text="", user_text="有風險嗎")
    assert should_block_repeat_call_dai(snap, artifact_text="同一則簡訊正文", user_text="你是誰")
    assert not should_block_repeat_call_dai(snap, artifact_text="完全不同的新簡訊內容", user_text="幫我看")
    assert is_follow_up_on_completed_review("你是誰", task_snapshot=snap, artifact_text="")


def test_validate_strips_call_dai_when_review_done() -> None:
    snap = {"review_phase": "review_completed", "artifact_key": "x"}
    todos = [PlanStep(skill="call_dai", args={"artifact": "x"})]
    out_todos, tt, ts, _ = validate_planner_output(
        user_text="你是誰",
        task_type="check",
        task_state="running",
        todos=todos,
        message="",
        task_snapshot=snap,
    )
    assert out_todos == []
    assert tt == "direct_response"


@patch("dual_agent.cai.plan_execute.invoke_planner")
@patch("dual_agent.cai.plan_execute.invoke_replan")
def test_run_plan_after_review_uses_planner(mock_replan, mock_planner) -> None:
    mock_planner.return_value = PlannerOutput(
        task_type="direct_response",
        task_state="answering",
        todos=[],
        message="依工作狀態回答",
    )
    mock_replan.return_value = ReplanOutput(
        complete=True,
        final_answer="依先前審查，風險偏低。",
        updated_todos=[],
        task_state="completed",
    )

    ctx = SkillContext(user_input="先前那則簡訊還安全嗎")
    ctx.policy_state["task_snapshot"] = {
        "review_phase": "review_completed",
        "artifact_key": "已審正文",
        "last_risk_score": 15,
    }
    mem = SessionMemory()
    mem.task_snapshot = dict(ctx.policy_state["task_snapshot"])
    out = run_plan_and_execute(
        user_text="先前那則簡訊還安全嗎",
        ctx=ctx,
        guard_source="chat_box",
        context_pack=pack_context(mem),
    )
    assert out.answer
    assert mock_planner.called
    assert mock_planner.call_args.kwargs.get("task_snapshot") == ctx.policy_state["task_snapshot"]
