"""固定多輪問答回歸：ask_user -> call_dai -> follow-up。"""

from __future__ import annotations

from desktop_cai_app import _build_memory_assistant_text
from dual_agent.cai.context_layer import SessionMemory, build_plan_summary, pack_context, record_turn
from dual_agent.cai.executor import format_results_for_display
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.schemas import PlanExecuteOutcome, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext, SkillResult

import dual_agent.cai.plan_execute as plan_execute


def _record_desktop_style_turn(
    session: SessionMemory,
    *,
    user_text: str,
    outcome: PlanExecuteOutcome,
) -> str:
    assistant = _build_memory_assistant_text(outcome.answer, outcome.results)
    result_summary = format_results_for_display(outcome.results) if outcome.results else "（本輪無 Executor 結果）"
    record_turn(
        session,
        user=user_text,
        assistant=assistant,
        task_type=outcome.task_type,
        task_state=outcome.task_state,
        model="fake",
        base_url="http://127.0.0.1:11434",
        plan_summary=build_plan_summary(outcome.plan),
        result_summary=result_summary,
    )
    return assistant


def test_multi_turn_review_regression_keeps_memory_clean_for_followup(monkeypatch) -> None:
    session = SessionMemory()
    ctx = SkillContext(user_input="")
    captured: dict[str, str] = {}
    executed: list[object] = []

    def fake_invoke_planner(
        *,
        user_text: str,
        source_turn_text: str | None = None,
        tool_catalog: list[dict[str, object]],
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        ingress_summary: str | None = None,
        ingress_detected_task_type: str = "",
        ingress_artifact_text: str = "",
        pending_review: bool = False,
    ) -> PlannerOutput:
        assert tool_catalog
        assert user_text == "我現在該怎麼辦?"
        assert source_turn_text == "我現在該怎麼辦?"
        assert ingress_detected_task_type == "unknown"
        assert ingress_artifact_text == ""
        assert pending_review is False
        cp = context_pack or ""
        captured["planner_context_pack"] = cp
        assert "【DAI 風險摘要】" in cp
        assert "風險分數：95/100" in cp
        assert "高風險勒索訊息" in cp
        assert '"context_pack": "（已省略）"' in cp
        assert "計畫步驟數：" not in cp
        return PlannerOutput(task_type="direct_response", task_state="answering", todos=[], message="依前文回答。")

    def fake_execute_step(step: object, _ctx: SkillContext) -> SkillResult:
        executed.append(step)
        skill = getattr(step, "skill", "")
        assert skill == "call_dai"
        args = getattr(step, "args", {})
        assert "3000萬" in str(args.get("artifact") or "")
        assert args.get("sms_review") is True
        return SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 95/100；高風險勒索",
            data={
                "dai": {
                    "risk_score": 95,
                    "recommended_cai_action": "block",
                    "safety_summary": "高風險勒索訊息",
                    "reason_highlights": ["要求支付 3000 萬", "包含人身威脅"],
                }
            },
        )

    def fake_invoke_replan(
        *,
        user_text: str,
        task_type: str,
        task_state: str,
        remaining_todos: list[object],
        observation_log: str | None,
        planner_message: str,
        model: str,
        base_url: str,
        temperature: float,
        context_pack: str | None = None,
        pending_review: bool = False,
    ) -> ReplanOutput:
        if "3000萬" in user_text:
            assert task_type == "check"
            assert task_state == "running"
            assert pending_review is False
            assert "call_dai" in (observation_log or "")
            assert "風險分數：95/100" in (observation_log or "")
            return ReplanOutput(
                complete=True,
                final_answer="這是高風險勒索訊息。風險分數 95/100，請先報警，不要付款。",
                updated_todos=[],
                task_state="completed",
                waiting_input=False,
                user_prompt="",
            )

        assert user_text == "我現在該怎麼辦?"
        assert task_type == "direct_response"
        assert task_state == "answering"
        assert pending_review is False
        captured["replan_context_pack"] = context_pack or ""
        assert captured["replan_context_pack"] == captured["planner_context_pack"]
        assert planner_message == "依前文回答。"
        return ReplanOutput(
            complete=True,
            final_answer="請先聯絡警方與家人確認安全，保留訊息證據，不要付款。",
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )

    monkeypatch.setattr(plan_execute, "invoke_planner", fake_invoke_planner)
    monkeypatch.setattr(plan_execute, "execute_step", fake_execute_step)
    monkeypatch.setattr(plan_execute, "invoke_replan", fake_invoke_replan)

    turn1 = "有人發簡訊給我"
    out1 = run_plan_and_execute(user_text=turn1, ctx=ctx, context_pack=pack_context(session))
    assert out1.task_type == "check"
    assert out1.task_state == "waiting_input"
    assert len(out1.plan) == 1
    assert out1.plan[0].skill == "ask_user"
    assert "請貼上完整簡訊或訊息內容" in out1.answer
    assert ctx.policy_state.get("pending_review")
    _record_desktop_style_turn(session, user_text=turn1, outcome=out1)

    turn2 = "他說要我給她3000萬 不然就殺了我"
    out2 = run_plan_and_execute(user_text=turn2, ctx=ctx, context_pack=pack_context(session))
    assert len(executed) == 1
    assert out2.task_type == "check"
    assert out2.task_state == "completed"
    assert out2.plan[0].skill == "call_dai"
    assert "風險分數 95/100" in out2.answer
    assert not ctx.policy_state.get("pending_review")
    assistant_turn2 = _record_desktop_style_turn(session, user_text=turn2, outcome=out2)
    assert "【DAI 風險摘要】" in assistant_turn2
    assert "計畫步驟數：" not in assistant_turn2

    turn3 = "我現在該怎麼辦?"
    out3 = run_plan_and_execute(user_text=turn3, ctx=ctx, context_pack=pack_context(session))
    assert out3.task_type == "direct_response"
    assert out3.task_state == "completed"
    assert out3.answer == "請先聯絡警方與家人確認安全，保留訊息證據，不要付款。"


def test_recorded_call_dai_turn_feeds_clean_context_pack() -> None:
    session = SessionMemory()
    outcome = PlanExecuteOutcome(
        plan=[
            plan_execute.PlanStep(
                skill="call_dai",
                args={
                    "artifact": "你男友在我手上，給我500萬",
                    "user_text": "請審查這則威脅訊息",
                    "context_pack": "【最近對話緩衝】很長很長的內容",
                    "sms_review": True,
                },
            )
        ],
        results=[
            SkillResult(
                ok=True,
                skill="call_dai",
                summary="[DAI] 風險分數 88/100；高風險",
                data={
                    "dai": {
                        "risk_score": 88,
                        "recommended_cai_action": "block",
                        "safety_summary": "高風險威脅訊息",
                        "reason_highlights": ["要求支付大額金錢"],
                    }
                },
            )
        ],
        answer="請立即報警並保留證據。",
        task_type="check",
        task_state="completed",
    )

    assistant = _record_desktop_style_turn(session, user_text="他傳簡訊威脅我", outcome=outcome)
    packed = pack_context(session)

    assert "【DAI 風險摘要】" in assistant
    assert "計畫步驟數：" not in assistant
    assert "請立即報警並保留證據。" in packed
    assert "【DAI 風險摘要】" in packed
    assert '"context_pack": "（已省略）"' in packed
    assert "很長很長的內容" not in packed
