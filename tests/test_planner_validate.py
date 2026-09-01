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


def test_strips_search_for_meta_question_about_searching() -> None:
    todos = [
        PlanStep(
            skill="search_web",
            args={"query": "我再問妳問題，你怎麼在搜尋網頁"},
        )
    ]
    out_t, tt, ts, msg = validate_planner_output(
        user_text="我再問妳問題，你怎麼在搜尋網頁",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
    )
    assert out_t == []
    assert tt == "direct_response"
    assert ts == "answering"
    assert "校正" in msg


def test_strips_search_for_capability_with_typo() -> None:
    todos = [PlanStep(skill="search_web", args={"query": "如何處裡問題"})]
    out_t, tt, ts, _msg = validate_planner_output(
        user_text="好吧，那你可以幫我處裡甚麼",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
    )
    assert out_t == []
    assert tt == "direct_response"
    assert ts == "answering"


def test_meta_detects_single_ni() -> None:
    assert meta_assistant_or_chat_scope("你")


def test_strips_call_dai_when_unknown_ingress_no_artifact() -> None:
    """IT 閒聊猜謎：Planner 誤排 call_dai 應被剝除。"""
    todos = [PlanStep(skill="call_dai", args={})]
    out_t, tt, ts, msg = validate_planner_output(
        user_text="做it有很多方面，你猜是哪個方面的",
        task_type="check",
        task_state="running",
        todos=todos,
        message="需要審查這則訊息",
        ingress_detected_task_type="unknown",
        ingress_artifact_text="",
        ingress_requires_dai=False,
        review_pending_candidate=False,
        pending_review=False,
    )
    assert out_t == []
    assert tt == "direct_response"
    assert ts == "answering"
    assert "校正" in msg
    assert "call_dai" in msg


def test_strips_call_dai_when_action_ingress_no_artifact() -> None:
    todos = [PlanStep(skill="call_dai", args={})]
    out_t, tt, ts, _ = validate_planner_output(
        user_text="你好，今天心情不錯",
        task_type="check",
        task_state="running",
        todos=todos,
        message="",
        ingress_detected_task_type="action",
        ingress_artifact_text="",
        ingress_requires_dai=False,
        review_pending_candidate=False,
        pending_review=False,
    )
    assert out_t == []
    assert tt == "direct_response"
    assert ts == "answering"


def test_keeps_call_dai_when_review_pending_candidate() -> None:
    """審查候選仍應走 ask_user，不由 misplaced strip 攔截。"""
    todos = [PlanStep(skill="call_dai", args={})]
    out_t, tt, ts, msg = validate_planner_output(
        user_text="我收到一則簡訊",
        task_type="check",
        task_state="new",
        todos=todos,
        message="",
        ingress_detected_task_type="unknown",
        ingress_artifact_text="",
        ingress_requires_dai=False,
        review_pending_candidate=True,
        pending_review=False,
    )
    assert len(out_t) == 1
    assert out_t[0].skill == "ask_user"
    assert tt == "check"
    assert ts == "waiting_input"
    assert "待審" in msg


def test_keeps_call_dai_when_check_ingress_with_artifact() -> None:
    body = "【XX銀行】您的帳戶異常，請點擊 https://fake-bank.com 完成驗證"
    todos: list[PlanStep] = []
    out_t, tt, ts, _ = validate_planner_output(
        user_text=f"幫我看這是不是詐騙：{body}",
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text=body,
        ingress_requires_dai=True,
        review_pending_candidate=False,
        pending_review=False,
    )
    assert len(out_t) == 1
    assert out_t[0].skill == "call_dai"
    assert tt == "check"
    assert ts == "running"
