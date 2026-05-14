"""DAI：defense_execute 與 invoke_dai（mock LLM，不依賴 Ollama）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.dai.defense_execute import execute_defense_step, run_defense_execute_legacy
from dual_agent.dai.invoke import invoke_dai
from dual_agent.dai.schemas import DAIRequest, DefenseObservation, DefensePlan, DefenseReplanOutput, DefenseStep


def test_execute_noop() -> None:
    req = DAIRequest(user_text="hi")
    obs = execute_defense_step(DefenseStep(skill="noop", args={}), req)
    assert obs.ok and obs.skill == "noop"


def test_execute_unknown_skill() -> None:
    req = DAIRequest(user_text="hi")
    obs = execute_defense_step(DefenseStep(skill="unknown_xyz", args={}), req)
    assert obs.ok is False


def test_run_defense_execute_legacy() -> None:
    plan = DefensePlan(
        risk_score=42,
        risk_labels=["測試"],
        safety_summary="摘要",
        evidence=[{"source": "unit", "note": "n"}],
        tool_restrictions={"x": 1},
        recommended_cai_action="continue",
        defense_todos=[DefenseStep(skill="noop", args={})],
    )
    r = run_defense_execute_legacy(plan, DAIRequest(user_text="u"))
    assert r.ok
    assert r.risk_score == 42
    assert len(r.defense_observations) == 1


def _turn_complete(**kwargs: object) -> DefenseReplanOutput:
    return DefenseReplanOutput(
        complete=True,
        next_defense_step=None,
        risk_score=int(kwargs.get("risk_score", 10)),
        risk_labels=list(kwargs.get("risk_labels") or []),
        safety_summary=str(kwargs.get("safety_summary") or "ok"),
        evidence=list(kwargs.get("evidence") or []),
        tool_restrictions=dict(kwargs.get("tool_restrictions") or {}),
        recommended_cai_action="continue",  # type: ignore[arg-type]
    )


def _turn_step_then_complete() -> list[DefenseReplanOutput]:
    return [
        DefenseReplanOutput(
            complete=False,
            next_defense_step=DefenseStep(skill="noop", args={}),
            risk_score=0,
            risk_labels=[],
            safety_summary="",
            evidence=[],
            tool_restrictions={},
            recommended_cai_action="continue",  # type: ignore[arg-type]
        ),
        _turn_complete(risk_score=10, safety_summary="done"),
    ]


def test_invoke_dai_replan_loop_mock() -> None:
    seq = _turn_step_then_complete()
    with patch("dual_agent.dai.invoke.invoke_defense_replan", side_effect=seq):
        out = invoke_dai(DAIRequest(user_text="test"), model="m", base_url="http://localhost:11434")
    assert out.ok
    assert out.risk_score == 10
    assert len(out.defense_observations) == 1
    assert out.defense_llm_turns == 2


def test_invoke_dai_sms_review_mock() -> None:
    plan = DefensePlan(
        risk_score=5,
        risk_labels=["plan"],
        safety_summary="計畫摘要",
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="continue",  # type: ignore[arg-type]
        defense_todos=[
            DefenseStep(skill="noop", args={}),
            DefenseStep(skill="noop", args={}),
        ],
    )
    with patch("dual_agent.dai.invoke.invoke_defense_review_sms_plan", return_value=plan):
        with patch("dual_agent.dai.invoke.execute_defense_step") as m_ex:
            m_ex.side_effect = [
                DefenseObservation(skill="noop", ok=True, summary="a", data={}),
                DefenseObservation(skill="noop", ok=True, summary="b", data={}),
            ]
            out = invoke_dai(
                DAIRequest(user_text="請審查簡訊", artifact="測試內容", sms_review=True),
                model="m",
                base_url="http://localhost:11434",
            )
    assert out.ok
    assert out.defense_llm_turns == 1
    assert len(out.defense_observations) == 2
    assert m_ex.call_count == 2
