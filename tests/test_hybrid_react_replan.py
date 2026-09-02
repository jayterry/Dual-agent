"""ReAct → ReplanOutput 轉接測試。"""

from __future__ import annotations

from dual_agent.cai.hybrid.react_replan import react_to_replan_output
from dual_agent.cai.hybrid.schemas import MessageFeatures, ReActAction, ReActOutput, TurnIntent
from dual_agent.cai.schemas import PlanStep


def test_react_finish_maps_to_replan_complete() -> None:
    ro = react_to_replan_output(
        ReActOutput(
            thought="完成",
            action=ReActAction(type="finish", final_answer="風險偏低。"),
        ),
        features=None,
        fallback_task_state="running",
    )
    assert ro.complete
    assert ro.final_answer == "風險偏低。"
    assert ro.updated_todos == []
    assert ro.task_state == "completed"


def test_react_tool_maps_to_single_todo() -> None:
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="review_sms"))
    ro = react_to_replan_output(
        ReActOutput(
            thought="送審",
            action=ReActAction(
                type="tool",
                skill="call_dai",
                args={"artifact": "test body", "sms_review": True},
            ),
        ),
        features=features,
    )
    assert ro.complete is False
    assert len(ro.updated_todos) == 1
    assert ro.updated_todos[0].skill == "call_dai"


def test_react_blocks_disallowed_skill() -> None:
    features = MessageFeatures(turn_intent=TurnIntent(primary_goal="out_of_scope"))
    ro = react_to_replan_output(
        ReActOutput(
            thought="不該 call",
            action=ReActAction(type="tool", skill="call_dai", args={}),
        ),
        features=features,
    )
    assert ro.complete is True
    assert ro.updated_todos == []
