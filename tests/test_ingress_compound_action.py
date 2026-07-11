"""Phase 0：複合動作句不應因 URL 而整句升格為防詐送審。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.review_entry_eligibility import looks_like_action_workflow
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.ingress import extract_entities, normalize_ingress
from dual_agent.skill_types import SkillContext, SkillResult

_COMPOUND_WEATHER_URL = "搜尋台北今天天氣，再幫我開 https://github.com"
_BANK_SCAM = "【XX銀行】您的帳戶異常，請點擊 https://fake-bank.com 完成驗證"


def test_compound_weather_and_open_url_not_requires_dai() -> None:
    out = normalize_ingress(raw_input_text=_COMPOUND_WEATHER_URL, input_origin="chat_box")
    assert str(out.detected_task_type) == "action"
    assert out.requires_dai is False
    assert (out.artifact_text or "").strip() == ""
    assert out.metadata.get("action_workflow") is True


def test_review_intent_with_url_still_requires_dai() -> None:
    raw = "幫我看這是不是詐騙：https://fake.com"
    out = normalize_ingress(raw_input_text=raw, input_origin="chat_box")
    assert str(out.detected_task_type) == "check"
    assert out.requires_dai is True
    assert "fake.com" in (out.artifact_text or "")


def test_open_url_only_is_action_not_dai() -> None:
    out = normalize_ingress(raw_input_text="打開 https://google.com", input_origin="chat_box")
    assert str(out.detected_task_type) == "action"
    assert out.requires_dai is False
    assert (out.artifact_text or "").strip() == ""


def test_bank_scam_body_still_requires_dai() -> None:
    out = normalize_ingress(raw_input_text=_BANK_SCAM, input_origin="chat_box")
    assert str(out.detected_task_type) == "check"
    assert out.requires_dai is True
    assert _BANK_SCAM in (out.artifact_text or "")


def test_looks_like_action_workflow_helper() -> None:
    ents = extract_entities(_COMPOUND_WEATHER_URL)
    assert looks_like_action_workflow(_COMPOUND_WEATHER_URL, ents) is True
    assert looks_like_action_workflow(_BANK_SCAM, extract_entities(_BANK_SCAM)) is False


def test_validate_does_not_force_call_dai_when_ingress_action() -> None:
    todos = [
        PlanStep(skill="weather", args={"location": "台北"}),
        PlanStep(skill="open_url_readonly", args={"url": "https://github.com"}),
    ]
    out_todos, tt, ts, _msg = validate_planner_output(
        user_text=_COMPOUND_WEATHER_URL,
        task_type="action",
        task_state="running",
        todos=todos,
        message="",
        ingress_detected_task_type="action",
        ingress_artifact_text="",
        ingress_requires_dai=False,
    )
    assert out_todos == todos
    assert tt == "action"
    assert not any(s.skill == "call_dai" for s in out_todos)


def test_plan_execute_compound_action_does_not_call_dai() -> None:
    ctx = SkillContext(user_input="")
    executed: list[str] = []

    def fake_execute(step: object, _ctx: SkillContext) -> SkillResult:
        sk = getattr(step, "skill", "")
        executed.append(sk)
        return SkillResult(ok=True, skill=sk, summary=f"{sk} ok")

    def fake_invoke_planner(**_kwargs: object) -> PlannerOutput:
        return PlannerOutput(
            task_type="action",
            task_state="running",
            todos=[
                PlanStep(skill="weather", args={"location": "台北"}),
                PlanStep(
                    skill="open_url_readonly",
                    args={"url": "https://github.com"},
                ),
            ],
            message="",
        )

    def fake_invoke_replan(**_kwargs: object) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="done",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.execute_step", side_effect=fake_execute):
            with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
                with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
                    out = run_plan_and_execute(user_text=_COMPOUND_WEATHER_URL, ctx=ctx)

    assert out.answer == "done"
    assert "call_dai" not in executed
    ingress = ctx.policy_state.get("ingress_payload") or {}
    assert ingress.get("requires_dai") is False
    assert ingress.get("detected_task_type") == "action"
