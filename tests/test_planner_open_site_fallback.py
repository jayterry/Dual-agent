"""Planner JSON 失敗時 open_site 降級。"""

from __future__ import annotations

from dual_agent.cai.planner_llm import _planner_open_site_fallback


def test_planner_open_site_fallback_google() -> None:
    out = _planner_open_site_fallback("幫我打開google")
    assert out is not None
    assert out.task_type == "action"
    assert len(out.todos) == 1
    assert out.todos[0].skill == "open_url_readonly"
    assert "google.com" in str(out.todos[0].args.get("url", ""))
