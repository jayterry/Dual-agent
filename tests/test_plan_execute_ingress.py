"""plan_execute：應在進 Planner 前先做 ingress normalize。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext, SkillResult


def test_run_plan_and_execute_passes_ingress_summary_to_planner() -> None:
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}

    def fake_invoke_planner(**kwargs: str) -> PlannerOutput:
        captured["source_turn_text"] = kwargs.get("source_turn_text") or ""
        captured["ingress_summary"] = kwargs.get("ingress_summary") or ""
        return PlannerOutput(task_type="check", task_state="running", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="ok",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    raw = "幫我看這是不是詐騙：【XX銀行】您的帳戶異常，請點擊 https://fake.com"
    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text=raw, ctx=ctx)

    assert out.answer == "ok"
    assert captured["source_turn_text"] == "幫我看這是不是詐騙"
    assert '"input_role": "mixed"' in captured["ingress_summary"]
    assert '"artifact_text": "【XX銀行】您的帳戶異常，請點擊 https://fake.com"' in captured["ingress_summary"]
    ingress = ctx.policy_state.get("ingress_payload") or {}
    assert ingress.get("intent_text") == "幫我看這是不是詐騙"
    assert ingress.get("artifact_text") == "【XX銀行】您的帳戶異常，請點擊 https://fake.com"


def test_review_request_without_artifact_planner_then_validate_ask_user() -> None:
    ctx = SkillContext(user_input="")

    def fake_invoke_planner(**_kwargs: str) -> PlannerOutput:
        """模擬 LLM 誤給空待辦；validate 會改為 ask_user。"""
        return PlannerOutput(task_type="check", task_state="new", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer=(
                "請貼上完整簡訊或訊息內容，我才能幫您進一步審查。"
                "若您本人或家人有立即危險，請先聯絡警方或當地緊急單位。"
            ),
            updated_todos=[],
            task_state="waiting_input",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text="有人發簡訊給她", ctx=ctx)
    assert out.task_type == "check"
    assert out.task_state == "waiting_input"
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert "請貼上完整簡訊或訊息內容" in out.answer
    assert "警方" in out.answer or "緊急單位" in out.answer
    assert ctx.policy_state.get("pending_review")


def test_scary_sms_content_without_body_still_asks_user() -> None:
    ctx = SkillContext(user_input="")

    def fake_invoke_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(task_type="check", task_state="new", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="請貼上完整簡訊或訊息內容。",
            updated_todos=[],
            task_state="waiting_input",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text="簡訊內容很可怕", ctx=ctx)
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert out.task_state == "waiting_input"


def test_pending_review_can_you_help_me_still_asks_user() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["pending_review"] = {"active": True}

    def fake_invoke_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(task_type="check", task_state="new", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="請貼上完整簡訊或訊息內容。",
            updated_todos=[],
            task_state="waiting_input",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text="你可以幫我看看嗎", ctx=ctx)
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert out.task_state == "waiting_input"


def test_pending_review_with_threat_body_routes_to_call_dai_not_search_web() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["pending_review"] = {"active": True}

    def fake_execute(step: object, ctx: SkillContext) -> SkillResult:
        skill = getattr(step, "skill", "")
        assert skill == "call_dai"
        ctx.policy_state.pop("pending_review", None)
        return SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 95/100；高風險勒索",
            data={
                "dai": {
                    "risk_score": 95,
                    "recommended_cai_action": "block",
                    "safety_summary": "高風險勒索訊息",
                    "reason_highlights": ["小孩被綁架", "要求支付 300 萬"],
                }
            },
        )

    def fake_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="已完成審查",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    raw = "簡訊說他的三個小孩被綁架了，要從最大的 alex 開始殺，除非給他 300 萬"

    def fake_invoke_planner(**kwargs: object) -> PlannerOutput:
        art = str(kwargs.get("ingress_artifact_text") or "").strip()
        ut = str(kwargs.get("source_turn_text") or "").strip()
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[
                PlanStep(
                    skill="call_dai",
                    args={
                        "artifact": art,
                        "user_text": ut or "請審查這則訊息",
                        "context_pack": "",
                        "sms_review": True,
                    },
                )
            ],
            message="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.execute_step", side_effect=fake_execute):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan):
                out = run_plan_and_execute(user_text=raw, ctx=ctx)
    assert len(out.plan) == 1
    assert out.plan[0].skill == "call_dai"
    assert out.task_type == "check"
    assert out.answer == "已完成審查"
    assert not ctx.policy_state.get("pending_review")


def test_threat_body_without_pending_review_still_routes_to_call_dai() -> None:
    ctx = SkillContext(user_input="")

    def fake_execute(step: object, ctx: SkillContext) -> SkillResult:
        assert getattr(step, "skill", "") == "call_dai"
        ctx.policy_state.pop("pending_review", None)
        return SkillResult(ok=True, skill="call_dai", summary="[DAI] ok", data={"dai": {"risk_score": 91}})

    def fake_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="已完成審查",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    raw = "簡訊說他的三個小孩被綁架了，要從最大的 alex 開始殺，除非給他 300 萬"

    def fake_invoke_planner(**kwargs: object) -> PlannerOutput:
        art = str(kwargs.get("ingress_artifact_text") or "").strip()
        ut = str(kwargs.get("source_turn_text") or "").strip()
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[
                PlanStep(
                    skill="call_dai",
                    args={
                        "artifact": art,
                        "user_text": ut or "請審查這則訊息",
                        "context_pack": "",
                        "sms_review": True,
                    },
                )
            ],
            message="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.execute_step", side_effect=fake_execute):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan):
                out = run_plan_and_execute(user_text=raw, ctx=ctx)
    assert len(out.plan) == 1
    assert out.plan[0].skill == "call_dai"
    assert out.task_type == "check"


def test_hello_does_not_create_pending_review() -> None:
    ctx = SkillContext(user_input="")

    def fake_invoke_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="你好",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text="你好", ctx=ctx)
    assert out.task_type == "direct_response"
    assert not ctx.policy_state.get("pending_review")


def test_iceland_context_does_not_create_pending_review_or_search() -> None:
    ctx = SkillContext(user_input="")

    def fake_invoke_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="")

    def fake_invoke_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="收到",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_invoke_replan):
            out = run_plan_and_execute(user_text="我現在在冰島", ctx=ctx)
    assert out.plan == []
    assert not ctx.policy_state.get("pending_review")
