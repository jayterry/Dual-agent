"""記憶檢索層：相關才注入 user_facts。"""

from __future__ import annotations

from dual_agent.cai.context_layer import (
    SessionMemory,
    build_context_pack,
    build_context_pack_for_turn,
    normalize_user_facts,
)
from dual_agent.cai.memory_retrieval import (
    looks_like_explicit_recall_turn,
    retrieve_memory_for_turn,
)


def test_explicit_recall_detects_who_question() -> None:
    assert looks_like_explicit_recall_turn("我媽媽是誰")
    assert looks_like_explicit_recall_turn("我專題組員有誰")


def test_explicit_recall_rejects_casual_comment() -> None:
    assert not looks_like_explicit_recall_turn("看起來你現在可以正常溝通了")
    assert not looks_like_explicit_recall_turn("謝謝")


def test_retrieve_injects_facts_only_for_recall() -> None:
    uf = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})
    casual = retrieve_memory_for_turn("看起來你現在可以正常溝通了", user_facts=uf)
    assert casual.inject_facts is False

    recall = retrieve_memory_for_turn("我媽媽是誰", user_facts=uf)
    assert recall.inject_facts is True


def test_build_context_pack_omits_yuri_on_casual_turn() -> None:
    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})
    session.user_facts = uf
    pack = build_context_pack_for_turn(session, "看起來你現在可以正常溝通了", user_facts=uf)
    assert "Yuri" not in pack
    assert "媽媽" not in pack or "本輪相關事實" not in pack


def test_build_context_pack_includes_yuri_on_recall() -> None:
    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["Yuri"]}})
    pack = build_context_pack_for_turn(session, "我媽媽是誰", user_facts=uf)
    assert "Yuri" in pack
    assert "本輪相關事實" in pack


def test_inventory_turn_injects_all_relations() -> None:
    session = SessionMemory()
    uf = normalize_user_facts({"relations": {"媽媽": ["yolo"]}})
    pack = build_context_pack_for_turn(session, "你現在記憶裡有甚麼", user_facts=uf)
    assert "yolo" in pack
    assert "本輪相關事實" in pack
