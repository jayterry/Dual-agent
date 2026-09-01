"""plan_execute：應在進 Planner 前先做 ingress normalize。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.review_entry_eligibility import looks_like_review_intent_without_artifact
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.ingress import extract_entities, normalize_ingress
from dual_agent.skill_types import SkillContext, SkillResult

_BANK_SCAM_BODY = "【XX銀行】您的帳戶異常，請點擊 https://fake-bank.com 完成驗證"


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


def test_review_request_without_artifact_short_circuits_before_planner() -> None:
    ctx = SkillContext(user_input="")
    planner = MagicMock()

    with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
        out = run_plan_and_execute(user_text="有人發簡訊給她", ctx=ctx)
    planner.assert_not_called()
    assert out.task_type == "check"
    assert out.task_state == "waiting_input"
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert out.results == []
    assert "請貼上完整簡訊內容" in out.answer
    assert ctx.policy_state.get("pending_review")


def test_review_intent_no_body_two_round_conversation() -> None:
    """Round 1：意圖句 → ask_user；Round 2：補正文 → call_dai（Planner 可誤排 call_dai，validate 放行）。"""
    round1 = "我剛剛收到一個簡訊，有點奇怪"
    ing1 = normalize_ingress(raw_input_text=round1, input_origin="chat_box")
    assert ing1.artifact_text == ""
    assert ing1.requires_dai is False
    assert ing1.metadata.get("review_pending_candidate") is True
    assert str(ing1.detected_task_type) == "check"

    ctx = SkillContext(user_input="")
    planner_r1 = MagicMock()
    with patch("dual_agent.cai.plan_execute.invoke_planner", planner_r1):
        out1 = run_plan_and_execute(user_text=round1, ctx=ctx)
    planner_r1.assert_not_called()
    assert out1.plan[0].skill == "ask_user"
    assert out1.task_state == "waiting_input"
    assert out1.results == []
    assert ctx.policy_state.get("pending_review")

    ing2 = normalize_ingress(raw_input_text=_BANK_SCAM_BODY, input_origin="chat_box")
    assert ing2.requires_dai is True
    assert (ing2.artifact_text or "").strip() == _BANK_SCAM_BODY

    def fake_execute(step: object, _ctx: SkillContext) -> SkillResult:
        assert getattr(step, "skill", "") == "call_dai"
        return SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 75/100",
            data={
                "dai": {
                    "risk_score": 75,
                    "recommended_cai_action": "warn",
                    "display_text": "風險分數：75/100\n判定：warn",
                    "safety_summary": "疑似釣魚",
                }
            },
        )

    def fake_invoke_planner(**kwargs: object) -> PlannerOutput:
        art = str(kwargs.get("ingress_artifact_text") or "").strip()
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[
                PlanStep(
                    skill="call_dai",
                    args={"artifact": art, "user_text": "請審查", "sms_review": True},
                )
            ],
            message="",
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

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=fake_invoke_planner):
        with patch("dual_agent.cai.plan_execute.execute_step", side_effect=fake_execute):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan):
                out2 = run_plan_and_execute(user_text=_BANK_SCAM_BODY, ctx=ctx)
    assert out2.plan[0].skill == "call_dai"
    dai = (out2.results[0].data or {}).get("dai") if out2.results else {}
    assert dai.get("risk_score") == 75


def test_planner_call_dai_blocked_when_review_pending_empty_artifact() -> None:
    """Round 1 句型：即使 mock Planner 回 call_dai，前置短路也不應執行。"""
    ctx = SkillContext(user_input="")

    def bad_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[PlanStep(skill="call_dai", args={"artifact": "meta", "sms_review": True})],
            message="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=bad_planner):
        out = run_plan_and_execute(user_text="我剛剛收到一個簡訊，有點奇怪", ctx=ctx)
    assert out.plan[0].skill == "ask_user"
    assert out.results == []


def test_sms_receipt_intent_no_artifact_full_spec() -> None:
    """規格：僅審查意圖、無正文 → pending_review + ask_user，不得 DAI／風險卡。"""
    user_text = "我剛剛收到一個簡訊，有點奇怪"
    ing = normalize_ingress(raw_input_text=user_text, input_origin="chat_box")
    assert str(ing.input_role) == "intent"
    assert ing.artifact_text == ""
    assert ing.requires_dai is False
    assert ing.metadata.get("review_pending_candidate") is True

    ctx = SkillContext(user_input="")

    def bad_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[
                PlanStep(
                    skill="call_dai",
                    args={"artifact": user_text, "user_text": user_text, "sms_review": True},
                )
            ],
            message="",
        )

    def bad_execute(step: object, _ctx: SkillContext) -> SkillResult:
        raise AssertionError("call_dai must not run")

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=bad_planner):
        with patch("dual_agent.cai.plan_execute.execute_step", side_effect=bad_execute):
            out = run_plan_and_execute(user_text=user_text, ctx=ctx)

    assert out.task_state == "waiting_input"
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert out.results == []
    assert ctx.policy_state.get("pending_review")
    ingress = ctx.policy_state.get("ingress_payload") or {}
    assert ingress.get("artifact_text") == ""
    assert ingress.get("requires_dai") is False
    for r in out.results:
        assert getattr(r, "skill", "") != "call_dai"
        dai = (getattr(r, "data", None) or {}).get("dai")
        assert not dai
    assert "risk_score" not in (out.answer or "")


def test_strange_sms_receipt_intent_no_dai() -> None:
    """「我收到一個奇怪的簡訊」不得 call_dai。"""
    user_text = "我收到一個奇怪的簡訊"
    ctx = SkillContext(user_input="")
    with patch("dual_agent.cai.plan_execute.invoke_planner") as planner:
        out = run_plan_and_execute(user_text=user_text, ctx=ctx)
    planner.assert_not_called()
    assert out.plan[0].skill == "ask_user"
    assert out.task_state == "waiting_input"
    assert not any(getattr(r, "skill", "") == "call_dai" for r in out.results)


def test_looks_like_review_intent_without_artifact_phrases() -> None:
    positives = (
        "我剛剛收到一個簡訊，有點奇怪",
        "我收到一個奇怪的簡訊",
        "幫我看看這是不是詐騙",
        "你可以幫我看嗎",
        "簡訊內容怪怪的",
        "有人傳簡訊給我",
        "收到一個可疑簡訊",
        "我收到一封怪怪的簡訊",
        "我剛收到一通奇怪訊息",
    )
    for s in positives:
        assert looks_like_review_intent_without_artifact(s, extract_entities(s)), s
    neg = "幫我看是不是詐騙：親愛的會員請點擊 http://evil.test/x"
    assert not looks_like_review_intent_without_artifact(neg, extract_entities(neg))


def test_scary_sms_content_without_body_still_asks_user() -> None:
    ctx = SkillContext(user_input="")
    planner = MagicMock()
    with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
        out = run_plan_and_execute(user_text="簡訊內容很可怕", ctx=ctx)
    planner.assert_not_called()
    assert len(out.plan) == 1
    assert out.plan[0].skill == "ask_user"
    assert out.task_state == "waiting_input"


def test_pending_review_can_you_help_me_still_asks_user() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["pending_review"] = {"active": True}
    planner = MagicMock()
    with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
        out = run_plan_and_execute(user_text="你可以幫我看看嗎", ctx=ctx)
    planner.assert_not_called()
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


def test_it_guess_call_dai_meta_only_skips_pending_review() -> None:
    """非審查 Ingress 的 artifact_meta_only 不應污染 pending_review。"""
    ctx = SkillContext(user_input="")
    user_text = "做it有很多方面，你猜是哪個方面的"

    def bad_planner(**_kwargs: str) -> PlannerOutput:
        return PlannerOutput(
            task_type="check",
            task_state="running",
            todos=[PlanStep(skill="call_dai", args={})],
            message="",
        )

    def fake_replan(**_kwargs: str) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="我猜你可能做資安方面的工作。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=bad_planner):
        with patch(
            "dual_agent.cai.plan_execute.validate_planner_output",
            side_effect=lambda **kw: (kw["todos"], kw["task_type"], kw["task_state"], kw["message"]),
        ):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan):
                out = run_plan_and_execute(user_text=user_text, ctx=ctx)

    assert not ctx.policy_state.get("pending_review")
    assert "請貼上完整簡訊" not in (out.answer or "")
    assert "資安" in (out.answer or "")
