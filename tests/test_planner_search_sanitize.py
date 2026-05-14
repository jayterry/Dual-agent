"""planner_context：接續字樣清理與連續 search_web 合併。"""

from __future__ import annotations

from dual_agent.cai.planner_context import (
    collapse_redundant_search_web,
    dedupe_search_web_in_plan,
    sanitize_search_web_query_string,
    strip_planner_system_prefix,
)
from dual_agent.cai.schemas import PlanStep


def test_strip_planner_prefix() -> None:
    raw = "【接續上一輪】先前問題：click search\n\ntask:weather"
    stripped = strip_planner_system_prefix(raw)
    assert "接續" not in stripped
    assert "task:weather" in stripped


def test_sanitize_query_removes_continuation() -> None:
    q = "【接續上一輪】先前問題：X\n\ntoday weather"
    s = sanitize_search_web_query_string(q)
    assert "接續" not in s
    assert "today weather" in s


def test_dedupe_three_near_duplicate_queries() -> None:
    todos = [
        PlanStep(skill="search_web", args={"query": "冰島國家公園路線 天氣"}),
        PlanStep(skill="search_web", args={"query": "冰島國家公園路線 天气"}),
        PlanStep(skill="search_web", args={"query": "冰島國家公園路線  天氣"}),
    ]
    out = dedupe_search_web_in_plan(todos)
    assert len(out) == 1

    todos = [
        PlanStep(
            skill="search_web",
            args={"query": "【接續上一輪】先前問題：A\n\ntask line"},
        ),
        PlanStep(skill="search_web", args={"query": "today weather"}),
    ]
    out = collapse_redundant_search_web(todos)
    assert len(out) == 1
    assert "today weather" in str(out[0].args.get("query", ""))
    assert "接續" not in str(out[0].args.get("query", ""))
