"""planner_context：搜尋意圖與 Context 補全 query（不依 Ollama）。"""

from __future__ import annotations

from dual_agent.cai.planner_context import (
    apply_explicit_search_guard,
    build_search_web_query,
    explicit_web_search_requested,
)
from dual_agent.cai.schemas import PlanStep


CTX_LOL = "【最近對話緩衝】\n使用者：我喜歡打英雄聯盟\n助理：好的。"


def test_direct_response_favorite_game_question_no_search() -> None:
    assert not explicit_web_search_requested("我喜歡的遊戲是什麼？")
    todos, tt, _ = apply_explicit_search_guard(
        user_text="我喜歡的遊戲是什麼？",
        context_pack=CTX_LOL,
        todos=[],
        task_type="direct_response",
        task_state="answering",
    )
    assert todos == []
    assert tt == "direct_response"


def test_search_favorite_game_resolves_lol_from_context() -> None:
    assert explicit_web_search_requested("搜尋我喜歡的遊戲")
    q = build_search_web_query("搜尋我喜歡的遊戲", CTX_LOL)
    assert "英雄聯盟" in q
    todos, tt, ts = apply_explicit_search_guard(
        user_text="搜尋我喜歡的遊戲",
        context_pack=CTX_LOL,
        todos=[],
        task_type="direct_response",
        task_state="answering",
    )
    assert len(todos) == 1
    assert todos[0].skill == "search_web"
    assert "英雄聯盟" in str(todos[0].args.get("query", ""))
    assert tt == "action"
    assert ts == "running"


def test_query_recent_updates_includes_tail() -> None:
    q = build_search_web_query("查詢我喜歡的遊戲最近更新", CTX_LOL)
    assert "英雄聯盟" in q
    assert "最近更新" in q


def test_introduce_lol_no_guard_injection() -> None:
    """「介紹」未帶上網動詞 → 不觸發強制 search_web。"""
    assert not explicit_web_search_requested("介紹英雄聯盟")
    todos, _, _ = apply_explicit_search_guard(
        user_text="介紹英雄聯盟",
        context_pack="（無）",
        todos=[],
        task_type="direct_response",
        task_state="answering",
    )
    assert todos == []


def test_online_search_lol() -> None:
    assert explicit_web_search_requested("上網查英雄聯盟")
    todos, _, _ = apply_explicit_search_guard(
        user_text="上網查英雄聯盟",
        context_pack="（無）",
        todos=[],
        task_type="direct_response",
        task_state="answering",
    )
    assert todos[0].skill == "search_web"
    assert "英雄聯盟" in str(todos[0].args.get("query", ""))


def test_force_replace_when_llm_wrong_first_skill() -> None:
    wrong = [PlanStep(skill="open_url", args={"url": "https://example.com"})]
    todos, tt, _ = apply_explicit_search_guard(
        user_text="搜尋我喜歡的遊戲",
        context_pack=CTX_LOL,
        todos=wrong,
        task_type="direct_response",
        task_state="answering",
    )
    assert todos[0].skill == "search_web"
    assert tt == "action"
