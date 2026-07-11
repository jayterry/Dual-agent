"""semantic_router 黃金測試集（沙盒，不需 Ollama）。"""

from __future__ import annotations

import pytest

from dual_agent.cai.semantic_router import (
    apply_semantic_router,
    route_user_text,
    split_clauses,
)
from dual_agent.cai.schemas import PlanStep


def _skills(result) -> list[str]:
    return [s.skill for s in result.todos]


def _args(result, skill: str) -> dict:
    for s in result.todos:
        if s.skill == skill:
            return s.args
    return {}


def test_split_compound_weather_and_url() -> None:
    parts = split_clauses("搜尋台北天氣，再開 https://github.com")
    assert len(parts) == 2
    assert "天氣" in parts[0]
    assert "github" in parts[1].lower()


def test_golden_compound_weather_open_url() -> None:
    r = route_user_text("搜尋台北天氣，再開 https://github.com")
    assert r.confidence == "high"
    assert r.task_type == "action"
    assert _skills(r) == ["weather", "open_url_readonly"]
    assert _args(r, "weather")["location"] == "台北"
    assert _args(r, "open_url_readonly")["url"] == "https://github.com"


def test_golden_weather_then_youtube() -> None:
    r = route_user_text("查台北天氣然後開 youtube")
    assert r.confidence == "high"
    assert _skills(r) == ["weather", "open_url_readonly"]
    assert _args(r, "weather")["location"] == "台北"
    assert "youtube.com" in _args(r, "open_url_readonly")["url"]


def test_golden_single_weather_kaohsiung() -> None:
    r = route_user_text("查高雄明天會不會下雨")
    assert r.confidence == "high"
    assert _skills(r) == ["weather"]
    assert _args(r, "weather")["location"] == "高雄"


def test_golden_google_search_stock() -> None:
    r = route_user_text("用 Google 搜台積電股價")
    assert r.confidence == "high"
    assert _skills(r) == ["search_web"]
    assert "台積電" in _args(r, "search_web")["query"]


def test_golden_open_google_only() -> None:
    r = route_user_text("打開 https://google.com")
    assert r.confidence == "high"
    assert _skills(r) == ["open_url_readonly"]
    assert "google.com" in _args(r, "open_url_readonly")["url"]


def test_golden_fetch_url_summary() -> None:
    r = route_user_text("讀 https://example.com 幫我摘要")
    assert r.confidence == "high"
    assert _skills(r) == ["fetch_url"]
    assert "example.com" in _args(r, "fetch_url")["url"]


def test_golden_hypothetical_sms_link_no_open() -> None:
    r = route_user_text("打開這則簡訊連結會怎樣")
    assert r.confidence == "high"
    assert r.task_type == "direct_response"
    assert r.todos == []


def test_golden_review_scam_with_url() -> None:
    r = route_user_text("幫我看這是不是詐騙：https://x.com")
    assert r.confidence == "high"
    assert r.task_type == "check"
    assert _skills(r) == ["call_dai"]
    assert "x.com" in _args(r, "call_dai")["artifact"]


def test_search_query_not_polluted_by_second_clause() -> None:
    """複合句不應把 URL／第二子句塞進 search query。"""
    r = route_user_text("搜尋台北天氣，再開 https://github.com")
    for s in r.todos:
        if s.skill == "search_web":
            q = str(s.args.get("query", ""))
            assert "github" not in q.lower()
            assert "再開" not in q
            pytest.fail("不應出現 search_web")


def test_low_confidence_vague_open_official_site() -> None:
    """「再開官網」無明確 URL 時不硬判。"""
    r = route_user_text("用 Google 搜台積電，再開官網")
    assert r.confidence == "low"


@pytest.mark.parametrize(
    ("text", "confidence", "skills", "checks"),
    [
        (
            "搜尋台北今天天氣，再幫我開 https://github.com",
            "high",
            ["weather", "open_url_readonly"],
            {"weather.location": "台北"},
        ),
        (
            "搜尋 Python 教學，再開 https://python.org",
            "high",
            ["search_web", "open_url_readonly"],
            {"search_web.query": "Python"},
        ),
        (
            "查台北天氣，搜尋台積電股價，再開 youtube",
            "high",
            ["weather", "search_web", "open_url_readonly"],
            {"weather.location": "台北"},
        ),
        ("打開google", "high", ["open_url_readonly"], {"open_url": "google.com"}),
        ("查詢台中即時天氣", "high", ["weather"], {"weather.location": "台中"}),
        ("台北今天天氣如何", "high", ["weather"], {"weather.location": "台北"}),
        ("幫我開 github", "high", ["open_url_readonly"], {"open_url": "github.com"}),
        (
            "讀 https://news.ycombinator.com 內容",
            "high",
            ["fetch_url"],
            {"fetch_url": "news.ycombinator.com"},
        ),
        ("搜尋我喜歡的遊戲", "low", [], {}),
        ("介紹英雄聯盟", "low", [], {}),
        ("用google搜天氣", "low", [], {}),
        ("我收到一則簡訊", "low", [], {}),
        (
            "打開 https://evil.example/phish 會怎樣",
            "high",
            [],
            {"task_type": "direct_response"},
        ),
    ],
)
def test_parametrized_routing(
    text: str,
    confidence: str,
    skills: list[str],
    checks: dict,
) -> None:
    r = route_user_text(text)
    assert r.confidence == confidence
    assert _skills(r) == skills
    if "weather.location" in checks:
        assert _args(r, "weather")["location"] == checks["weather.location"]
    if "search_web.query" in checks:
        assert checks["search_web.query"] in _args(r, "search_web")["query"]
    if "open_url" in checks:
        assert checks["open_url"] in _args(r, "open_url_readonly")["url"]
    if "fetch_url" in checks:
        assert checks["fetch_url"] in _args(r, "fetch_url")["url"]
    if checks.get("task_type"):
        assert r.task_type == checks["task_type"]


def test_apply_semantic_router_overrides_wrong_planner_todos() -> None:
    wrong = [
        PlanStep(
            skill="search_web",
            args={"query": "搜尋台北天氣，再開 https://github.com"},
        )
    ]
    todos, tt, ts, applied = apply_semantic_router(
        user_text="搜尋台北天氣，再開 https://github.com",
        todos=wrong,
        task_type="action",
        task_state="running",
        ingress_requires_dai=False,
        ingress_detected_task_type="action",
    )
    assert applied is True
    assert [s.skill for s in todos] == ["weather", "open_url_readonly"]
    assert todos[0].args["location"] == "台北"
    assert "github.com" in todos[1].args["url"]
    assert tt == "action"
    assert ts == "running"


def test_apply_semantic_router_skips_when_ingress_requires_dai() -> None:
    wrong = [PlanStep(skill="open_url_readonly", args={"url": "https://fake-bank.com"})]
    todos, tt, ts, applied = apply_semantic_router(
        user_text="【XX銀行】請點擊 https://fake-bank.com 驗證",
        todos=wrong,
        task_type="check",
        task_state="running",
        ingress_requires_dai=True,
        ingress_detected_task_type="check",
    )
    assert applied is False
    assert todos == wrong
    assert tt == "check"
    assert ts == "running"

