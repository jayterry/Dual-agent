"""記憶：多人 relations、追加、忘記、姓名正規化、空查詢。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.context_layer import (
    SessionMemory,
    append_relation_value,
    default_user_facts,
    format_relation_names,
    merge_relation_fact,
    normalize_relation,
    normalize_user_facts,
    pack_context,
)
from dual_agent.cai.memory_direct import (
    build_confirm_question,
    is_affirmative_reply,
    looks_like_forget_memory_turn,
    looks_like_memory_clarification_turn,
    normalize_person_name,
    try_handle_memory_turn,
    try_parse_additive_name,
    try_recall_empty_relation,
    try_recall_from_user_facts,
)
from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import _pending_review_followup_should_drop_dai
from dual_agent.skill_types import SkillContext


def test_normalize_relation_aliases() -> None:
    assert normalize_relation("母親") == "媽媽"
    assert normalize_relation("爸") == "爸爸"


def test_relations_multi_value_normalize() -> None:
    uf = normalize_user_facts({"relations": {"專題組員": ["ruby", "David"]}})
    assert uf["relations"]["專題組員"] == ["ruby", "David"]
    uf2 = normalize_user_facts({"relations": {"媽媽": "Yuri"}})
    assert uf2["relations"]["媽媽"] == ["Yuri"]


def test_build_confirm_question_append_mode() -> None:
    q = build_confirm_question("專題組員", "David", existing_names=["ruby"], mode="append")
    assert "David" in q
    assert "ruby" in q
    assert "嗎" in q


def test_additive_parse() -> None:
    assert try_parse_additive_name("還有David") == "David"
    assert try_parse_additive_name("还有 Jay") == "Jay"
    assert try_parse_additive_name("還有一個人，就Ossa") == "Ossa"
    assert normalize_person_name("叫做ossa") == "ossa"


def test_is_affirmative_deterministic() -> None:
    assert is_affirmative_reply("是")
    assert is_affirmative_reply("是的")
    assert not is_affirmative_reply("我有兩個組員")


def test_ruby_then_david_append_two_rounds() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = default_user_facts()

    def fake_parse(user_text: str, **_kwargs: object) -> dict | None:
        t = user_text.strip()
        if "yuri" in t.lower():
            return {"fact_type": "relation", "relation": "媽媽", "value": "Yuri", "mode": "set"}
        if "ruby" in t.lower():
            return {"fact_type": "relation", "relation": "專題組員", "value": "ruby", "mode": "set"}
        if "david" in t.lower():
            return {"fact_type": "relation", "relation": "專題組員", "value": "David", "mode": "append"}
        return None

    try_handle_memory_turn(
        "我的專題組員是ruby",
        ctx=ctx,
        user_facts=default_user_facts(),
        model="mock",
        base_url="http://localhost",
        parse_fn=fake_parse,
    )
    try_handle_memory_turn("是", ctx=ctx, user_facts=ctx.policy_state["user_facts"], model="mock", base_url="http://localhost", parse_fn=fake_parse)

    try_handle_memory_turn(
        "還有David",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=fake_parse,
    )
    out = try_handle_memory_turn(
        "是",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=fake_parse,
    )
    assert out is not None
    assert "已記住" in out.answer
    uf = normalize_user_facts(ctx.policy_state["user_facts"])
    assert uf["relations"]["專題組員"] == ["ruby", "David"]


def test_affirm_is_deterministic_without_llm_classify() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"專題組員": ["ruby"]}})
    ctx.policy_state["pending_memory_confirm"] = {
        "fact_type": "relation",
        "relation": "專題組員",
        "value": "David",
        "mode": "append",
        "question": build_confirm_question("專題組員", "David", existing_names=["ruby"], mode="append"),
    }

    llm_classify = MagicMock()
    out = try_handle_memory_turn(
        "是",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        classify_fn=llm_classify,
        parse_fn=lambda *_a, **_k: None,
        recall_fn=lambda *_a, **_k: None,
    )
    llm_classify.assert_not_called()
    assert out and "已記住" in out.answer
    assert normalize_user_facts(ctx.policy_state["user_facts"])["relations"]["專題組員"] == [
        "ruby",
        "David",
    ]


def test_recall_lists_both_members() -> None:
    uf = normalize_user_facts({"relations": {"專題組員": ["ruby", "David"]}})
    ans = try_recall_from_user_facts("我專題組員有誰", uf)
    assert ans
    assert "ruby" in ans and "David" in ans


def test_clarification_two_members() -> None:
    uf = normalize_user_facts({"relations": {"專題組員": ["ruby", "David"]}})
    ans = try_recall_from_user_facts("我有兩個組員", uf)
    assert ans
    assert "ruby" in ans and "David" in ans


def test_memory_clarification_drops_pending_review_dai() -> None:
    assert _pending_review_followup_should_drop_dai("我有兩個組員")
    assert looks_like_memory_clarification_turn("我有兩個組員")


def test_plan_execute_clears_pending_review_on_memory() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["pending_review"] = {"active": True}
    ctx.policy_state["user_facts"] = normalize_user_facts(
        {"relations": {"專題組員": ["ruby", "David"]}}
    )
    planner = MagicMock()
    with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
        out = run_plan_and_execute(user_text="我有兩個組員", ctx=ctx)
    planner.assert_not_called()
    assert not ctx.policy_state.get("pending_review")
    assert "ruby" in out.answer and "David" in out.answer


def test_context_pack_multi_bullet() -> None:
    mem = SessionMemory()
    merge_relation_fact(mem, "專題組員", "ruby")
    append_relation_value(mem, "專題組員", "David")
    pack = pack_context(mem)
    assert "- 專題組員：" in pack
    assert format_relation_names(["ruby", "David"]) in pack


def test_forget_clears_relations() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts(
        {"relations": {"專題組員": ["ruby", "Ossa"]}}
    )
    out = try_handle_memory_turn(
        "請忘記這兩個人，我換組員了",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=lambda *_a, **_k: None,
        recall_fn=lambda *_a, **_k: None,
    )
    assert out is not None
    assert "已忘記" in out.answer
    assert "ruby" not in out.answer
    uf = normalize_user_facts(ctx.policy_state["user_facts"])
    assert not uf["relations"].get("專題組員")
    assert looks_like_forget_memory_turn("請忘記這兩個人，我換組員了")


def test_forget_not_recalled_as_two_members() -> None:
    uf = normalize_user_facts({"relations": {"專題組員": ["ruby", "Ossa"]}})
    assert try_recall_from_user_facts("請忘記這兩個人，我換組員了", uf) is None


def test_ossa_additive_confirm_question() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"專題組員": ["ruby"]}})
    out = try_handle_memory_turn(
        "還有一個人，就Ossa",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=lambda *_a, **_k: None,
        recall_fn=lambda *_a, **_k: None,
    )
    assert out is not None
    assert "Ossa" in out.answer
    assert "一個人，就Ossa" not in out.answer
    pending = ctx.policy_state.get("pending_memory_confirm") or {}
    assert pending.get("value") == "Ossa"


def test_empty_recall_no_planner() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = default_user_facts()
    planner = MagicMock()
    with patch("dual_agent.cai.plan_execute.invoke_planner", planner):
        out = run_plan_and_execute(user_text="我的專題組員現在有誰", ctx=ctx)
    planner.assert_not_called()
    assert "尚未記錄" in out.answer


def test_empty_recall_helper() -> None:
    assert try_recall_empty_relation("我的專題組員現在有誰", default_user_facts())
    assert "尚未記錄" in (try_recall_empty_relation("我的專題組員現在有誰", default_user_facts()) or "")


def test_after_forget_empty_recall() -> None:
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts({"relations": {"專題組員": ["ruby"]}})
    try_handle_memory_turn(
        "請忘記這兩個人",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=lambda *_a, **_k: None,
        recall_fn=lambda *_a, **_k: None,
    )
    out = try_handle_memory_turn(
        "我的專題組員有誰",
        ctx=ctx,
        user_facts=ctx.policy_state["user_facts"],
        model="mock",
        base_url="http://localhost",
        parse_fn=lambda *_a, **_k: None,
        recall_fn=lambda *_a, **_k: None,
    )
    assert out and "尚未記錄" in out.answer
