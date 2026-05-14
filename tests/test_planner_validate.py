"""planner_validate：誤排 search_web 的校正。"""

from __future__ import annotations

from dual_agent.cai.planner_validate import meta_assistant_or_chat_scope, validate_planner_output
from dual_agent.cai.schemas import PlanStep


def test_strips_search_for_capability_question() -> None:
    todos = [PlanStep(skill="search_web", args={"query": "你可以做甚麼"})]
    out_t, tt, ts, msg = validate_planner_output(
        user_text="我想知道你可以做甚麼",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
    )
    assert out_t == []
    assert tt == "direct_response"
    assert ts == "answering"
    assert "校正" in msg


def test_strips_when_direct_response_plus_search() -> None:
    todos = [PlanStep(skill="search_web", args={"query": "x"})]
    out_t, _, _, _ = validate_planner_output(
        user_text="隨便一句不觸發 meta",
        task_type="direct_response",
        task_state="answering",
        todos=todos,
        message="",
    )
    assert out_t == []


def test_keeps_search_when_explicit_user_request() -> None:
    todos = [PlanStep(skill="search_web", args={"query": "天氣"})]
    out_t, tt, _, _ = validate_planner_output(
        user_text="搜尋今日天氣",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
    )
    assert len(out_t) == 1
    assert tt == "action"


def test_meta_detects_intro_name() -> None:
    assert meta_assistant_or_chat_scope("我叫alex")


def test_meta_detects_replan_question() -> None:
    assert meta_assistant_or_chat_scope("Replan 能做哪些任務")


def test_pending_review_search_is_corrected_to_ask_user() -> None:
    todos = [PlanStep(skill="search_web", args={"query": "如何應對威脅簡訊"})]
    out_t, tt, ts, msg = validate_planner_output(
        user_text="你可以幫我看看嗎",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
        pending_review=True,
    )
    assert len(out_t) == 1
    assert out_t[0].skill == "ask_user"
    assert tt == "check"
    assert ts == "waiting_input"
    assert "ask_user" in msg


def test_check_without_artifact_is_corrected_to_ask_user() -> None:
    out_t, tt, ts, msg = validate_planner_output(
        user_text="有人發簡訊給她",
        task_type="check",
        task_state="new",
        todos=[],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=False,
    )
    assert len(out_t) == 1
    assert out_t[0].skill == "ask_user"
    assert tt == "check"
    assert ts == "waiting_input"
    assert "待審內容" in msg
