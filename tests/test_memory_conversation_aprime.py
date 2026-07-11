"""A' 沙盒：記憶對話一致性（yolo 劇本，不依賴 Ollama）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.cai.context_layer import build_context_pack_for_turn, normalize_user_facts
from dual_agent.cai.memory_direct import try_handle_memory_turn
from dual_agent.cai.memory_manager.schemas import MemoryDecision
from dual_agent.cai.schemas import PlannerOutput, ReplanOutput
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.skill_types import SkillContext


def _affirm_yolo_flow(ctx: SkillContext) -> None:
    """模擬：我媽媽是 yolo → 確認 → 寫入。"""
    calls: list[str] = []

    def fake_llm(user_text: str, *_a, **_k) -> MemoryDecision:
        calls.append(user_text)
        if "媽媽" in user_text and "yolo" in user_text.lower():
            return MemoryDecision(
                intent="remember_set",
                relation="媽媽",
                value="yolo",
                mode="set",
                confidence=0.95,
            )
        return MemoryDecision(intent="none", confidence=0.0)

    with patch(
        "dual_agent.cai.memory_manager.manager.invoke_memory_turn_llm",
        side_effect=fake_llm,
    ):
        out1 = try_handle_memory_turn(
            "我的媽媽是yolo",
            ctx=ctx,
            user_facts=ctx.policy_state.get("user_facts"),
            model="mock",
            base_url="http://localhost",
        )
        assert out1 is not None
        assert "yolo" in (out1.answer or "").lower()
        assert ctx.policy_state.get("pending_memory_confirm")

        out2 = try_handle_memory_turn(
            "沒錯",
            ctx=ctx,
            user_facts=ctx.policy_state.get("user_facts"),
            model="mock",
            base_url="http://localhost",
        )
        assert out2 is not None
        assert "已記住" in (out2.answer or "")
        uf = normalize_user_facts(ctx.policy_state.get("user_facts"))
        assert uf.get("relations", {}).get("媽媽") == ["yolo"]


def test_inventory_lists_yolo_after_confirm() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts(None)
    _affirm_yolo_flow(ctx)

    with patch(
        "dual_agent.cai.memory_manager.manager.invoke_memory_turn_llm",
        return_value=MemoryDecision(
            intent="clarify",
            answer="目前我還沒有記得任何事情。",
            confidence=0.5,
        ),
    ):
        out = try_handle_memory_turn(
            "你現在記憶裡有甚麼",
            ctx=ctx,
            user_facts=ctx.policy_state["user_facts"],
            model="mock",
            base_url="http://localhost",
        )
    assert out is not None
    assert "yolo" in (out.answer or "").lower()
    assert "沒有記得" not in (out.answer or "")


def test_contradiction_apologizes_and_lists_facts() -> None:
    ctx = SkillContext(user_input="")
    _affirm_yolo_flow(ctx)

    out = try_handle_memory_turn(
        "那你怎麼會說你沒記住任何事情",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
    )
    assert out is not None
    assert "yolo" in (out.answer or "").lower()
    assert "抱歉" in (out.answer or "")


def test_relation_only_recalls_without_reconfirm() -> None:
    ctx = SkillContext(user_input="")
    _affirm_yolo_flow(ctx)

    def fake_llm(*_a, **_k) -> MemoryDecision:
        return MemoryDecision(
            intent="remember_set",
            relation="媽媽",
            value="yolo",
            mode="set",
            confidence=0.9,
        )

    with patch(
        "dual_agent.cai.memory_manager.manager.invoke_memory_turn_llm",
        side_effect=fake_llm,
    ):
        out = try_handle_memory_turn(
            "我的媽媽",
            ctx=ctx,
            user_facts=ctx.policy_state["user_facts"],
            model="mock",
            base_url="http://localhost",
        )
    assert out is not None
    assert "yolo" in (out.answer or "").lower()
    assert "您是說" not in (out.answer or "")
    assert not ctx.policy_state.get("pending_memory_confirm")


def test_inventory_injects_facts_into_context_pack() -> None:
    from dual_agent.cai.context_layer import SessionMemory

    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["yolo"]}})
    pack = build_context_pack_for_turn(session, "你現在記憶裡有甚麼", user_facts=uf)
    assert "yolo" in pack
    assert "本輪相關事實" in pack


def test_casual_still_omits_facts_in_pack() -> None:
    from dual_agent.cai.context_layer import SessionMemory

    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["yolo"]}})
    pack = build_context_pack_for_turn(
        session,
        "看起來你現在可以正常溝通了",
        user_facts=uf,
    )
    assert "yolo" not in pack


def test_plan_execute_inventory_uses_deterministic_not_replan_leak() -> None:
    ctx = SkillContext(user_input="")
    _affirm_yolo_flow(ctx)
    from dual_agent.cai.context_layer import SessionMemory

    session = SessionMemory()
    pack = build_context_pack_for_turn(
        session,
        "你現在記憶裡有甚麼",
        user_facts=ctx.policy_state["user_facts"],
    )

    def bad_replan(**_kwargs) -> ReplanOutput:
        return ReplanOutput(
            complete=True,
            final_answer="目前我還沒有記得任何事情。",
            updated_todos=[],
            task_state="completed",
        )

    with patch("dual_agent.cai.plan_execute.invoke_planner") as mock_planner:
        with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=bad_replan):
            out = run_plan_and_execute(
                user_text="你現在記憶裡有甚麼",
                ctx=ctx,
                context_pack=pack,
            )
    mock_planner.assert_not_called()
    assert "yolo" in (out.answer or "").lower()
    assert "沒有記得" not in (out.answer or "")
