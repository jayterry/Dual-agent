"""整合：未詢問不得主動洩漏記憶；明確問才注入 context。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.context_layer import build_context_pack_for_turn, normalize_user_facts
from dual_agent.cai.memory_manager.schemas import MemoryDecision
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.schemas import PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext


def _fake_replan_casual(**_kwargs) -> ReplanOutput:
    return ReplanOutput(
        complete=True,
        final_answer="好的，有什麼可以幫您的嗎？",
        updated_todos=[],
        task_state="completed",
    )


def _fake_replan_leaky(**_kwargs) -> ReplanOutput:
    return ReplanOutput(
        complete=True,
        final_answer="您的媽媽叫 Yuri。",
        updated_todos=[],
        task_state="completed",
    )


def test_memory_llm_recall_blocked_on_casual_comment() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})

    def fake_memory_llm(*_a, **_k) -> MemoryDecision:
        return MemoryDecision(intent="recall", relation="媽媽", confidence=0.9)

    with patch(
        "dual_agent.cai.memory_manager.manager.invoke_memory_turn_llm",
        side_effect=fake_memory_llm,
    ):
        from dual_agent.cai.memory_direct import try_handle_memory_turn

        out = try_handle_memory_turn(
            "看起來你現在可以正常溝通了",
            ctx=ctx,
            user_facts=ctx.policy_state["user_facts"],
            model="mock",
            base_url="http://localhost",
        )
    assert out is None


def test_casual_turn_context_has_no_yuri() -> None:
    from dual_agent.cai.context_layer import SessionMemory

    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})
    pack = build_context_pack_for_turn(
        session,
        "看起來你現在可以正常溝通了",
        user_facts=uf,
    )
    assert "Yuri" not in pack


def test_plan_execute_casual_without_facts_in_pack() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})
    from dual_agent.cai.context_layer import SessionMemory

    session = SessionMemory()
    pack = build_context_pack_for_turn(
        session,
        "看起來你現在可以正常溝通了",
        user_facts=ctx.policy_state["user_facts"],
    )
    assert "Yuri" not in pack

    def planner(**_kwargs) -> PlannerOutput:
        return PlannerOutput(
            task_type="direct_response",
            task_state="completed",
            todos=[],
            message="",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=planner):
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=_fake_replan_casual):
            with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
                out = run_plan_and_execute(
                    user_text="看起來你現在可以正常溝通了",
                    ctx=ctx,
                    context_pack=pack,
                )
    assert "Yuri" not in (out.answer or "")


def test_explicit_recall_still_works() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})

    def fake_memory_llm(*_a, **_k) -> MemoryDecision:
        return MemoryDecision(intent="recall", relation="媽媽", confidence=0.9)

    with patch(
        "dual_agent.cai.memory_manager.manager.invoke_memory_turn_llm",
        side_effect=fake_memory_llm,
    ):
        from dual_agent.cai.memory_direct import try_handle_memory_turn

        out = try_handle_memory_turn(
            "我媽媽是誰",
            ctx=ctx,
            user_facts=ctx.policy_state["user_facts"],
            model="mock",
            base_url="http://localhost",
        )
    assert out is not None
    assert "Yuri" in (out.answer or "")
