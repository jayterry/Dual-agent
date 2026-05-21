"""Replan 卡住時 deterministic 收尾。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.plan_execute import _try_deterministic_replan_finish, run_dai_then_replan
from dual_agent.cai.schemas import PlanStep, ReplanOutput
from dual_agent.skill_types import SkillContext, SkillResult


def test_try_deterministic_finish_from_call_dai() -> None:
    results = [
        SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 72/100",
            data={
                "dai": {
                    "risk_score": 72,
                    "verdict": "warn",
                    "recommended_cai_action": "ask_user",
                    "display_text": (
                        "風險分數：72/100\n判定：warn\n\n主要原因：\n• 高額借款\n\n建議：\n• 勿加 LINE"
                    ),
                    "user_reason_highlights": ["高額借款"],
                    "user_suggestions": ["勿加 LINE"],
                }
            },
        )
    ]
    ans = _try_deterministic_replan_finish(results)
    assert ans is not None
    assert "72/100" in ans
    assert "判定：warn" in ans


def test_run_dai_then_replan_when_replan_stuck() -> None:
    artifact = "【健保卡借款】以月計息，放款迅速，電洽：0979300280"

    def fake_replan(**_kwargs: object) -> ReplanOutput:
        return ReplanOutput(
            complete=False,
            final_answer="",
            updated_todos=[],
            task_state="running",
        )

    def fake_execute_step(step: PlanStep, ctx: SkillContext) -> SkillResult:
        return SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 30/100",
            data={
                "dai": {
                    "risk_score": 30,
                    "recommended_cai_action": "continue",
                    "safety_summary": "綜合風險 30/100。",
                    "reason_highlights": ["硬規則命中（25 分）"],
                }
            },
        )

    with (
        patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=fake_replan),
        patch("dual_agent.cai.plan_execute.execute_step", side_effect=fake_execute_step),
    ):
        out = run_dai_then_replan(
            message="請審查",
            artifact=artifact,
            ctx=SkillContext(user_input=artifact),
        )

    assert "待辦已空但 Replan" not in (out.answer or "")
    assert "30/100" in (out.answer or "") or "風險" in (out.answer or "")
