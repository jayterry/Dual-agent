"""review_entry_eligibility／ingress：宣告收到簡訊而無正文。"""

from __future__ import annotations

from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.schemas import PlanStep
from dual_agent.cai.review_entry_eligibility import looks_like_declarative_sms_receipt_only
from dual_agent.cai.skills.call_dai.handler import artifact_is_meta_only_intent
from dual_agent.ingress import extract_entities, normalize_ingress


def test_normalize_creepy_sms_receipt_is_check_pending_requires_no_dai() -> None:
    ing = normalize_ingress(raw_input_text="我收到一則詭異的簡訊", input_origin="chat_box")
    assert str(ing.detected_task_type) == "check"
    assert ing.artifact_text == ""
    assert ing.requires_dai is False
    assert ing.metadata.get("review_pending_candidate") is True


def test_declarative_sms_template_variants() -> None:
    for s in (
        "收到一封怪怪的簡訊",
        "我剛收到一通奇怪訊息",
        "我收到一則簡訊",
    ):
        assert looks_like_declarative_sms_receipt_only(s, extract_entities(s)), s


def test_colon_reply_is_not_meta_only_declaration() -> None:
    raw = "幫我看是不是詐騙：親愛的會員請點擊連結 http://evil.test/x"
    assert not looks_like_declarative_sms_receipt_only(raw, extract_entities(raw))


def test_planner_validator_strips_call_dai_when_ingress_artifact_empty() -> None:
    bad = PlanStep(skill="call_dai", args={"artifact": "anything", "sms_review": True})
    todos, tt, ts, msg = validate_planner_output(
        user_text="我收到詭異簡訊",
        task_type="check",
        task_state="running",
        todos=[bad],
        message="oops",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        ingress_requires_dai=False,
        review_pending_candidate=True,
    )
    assert len(todos) == 1
    assert todos[0].skill == "ask_user"
    assert tt == "check"


def test_artifact_dai_meta_handles_creepy_receipt_sentence() -> None:
    assert artifact_is_meta_only_intent("我收到一則詭異的簡訊")


def test_pending_review_keeps_call_dai_when_ingress_empty_but_body_in_step() -> None:
    step = PlanStep(skill="call_dai", args={"artifact": "借我3000萬周轉", "sms_review": True})
    todos, tt, ts, _ = validate_planner_output(
        user_text="借我3000萬周轉",
        task_type="check",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert len(todos) == 1
    assert todos[0].skill == "call_dai"
    assert "3000" in str((todos[0].args or {}).get("artifact") or "")
    assert tt == "check"
    assert ts == "running"


def test_pending_review_fills_empty_call_dai_artifact_from_user_text() -> None:
    step = PlanStep(skill="call_dai", args={"sms_review": True})
    todos, _, _, _ = validate_planner_output(
        user_text="借我3000萬周轉",
        task_type="check",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert todos[0].skill == "call_dai"
    assert "3000" in str((todos[0].args or {}).get("artifact") or "")


def test_pending_review_unknown_ingress_allows_follow_up_call_dai() -> None:
    step = PlanStep(skill="call_dai", args={"artifact": "借我3000萬周轉", "sms_review": True})
    todos, tt, _, _ = validate_planner_output(
        user_text="借我3000萬周轉",
        task_type="unknown",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="unknown",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert len(todos) == 1 and todos[0].skill == "call_dai"
    assert tt == "check"


def test_pending_review_meta_only_still_asks_user() -> None:
    step = PlanStep(skill="call_dai", args={"artifact": "我收到簡訊", "sms_review": True})
    todos, tt, ts, _ = validate_planner_output(
        user_text="我收到簡訊",
        task_type="check",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert len(todos) == 1
    assert todos[0].skill == "ask_user"
    assert tt == "check"
    assert ts == "waiting_input"


def test_pending_review_short_weather_turn_drops_misplaced_call_dai() -> None:
    step = PlanStep(skill="call_dai", args={"artifact": "anything", "sms_review": True})
    todos, tt, ts, _ = validate_planner_output(
        user_text="高雄今天天氣",
        task_type="check",
        task_state="running",
        todos=[step],
        message="",
        ingress_detected_task_type="check",
        ingress_artifact_text="",
        pending_review=True,
    )
    assert todos == []
    assert tt == "direct_response"
    assert ts == "answering"
