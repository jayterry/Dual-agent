"""plan_execute：回傳給 UI 的 plan 須反映實際執行過的步驟。"""

from __future__ import annotations

from dual_agent.cai.plan_execute import _out_plan
from dual_agent.cai.schemas import PlanStep


def test_out_plan_uses_executed_when_non_empty() -> None:
    ex = [PlanStep(skill="search_web", args={"query": "Apex Legends"})]
    out = _out_plan(initial=[], executed=ex)
    assert len(out) == 1
    assert out[0].skill == "search_web"


def test_out_plan_falls_back_to_initial() -> None:
    init = [PlanStep(skill="ask_user", args={"question": "hi"})]
    out = _out_plan(initial=init, executed=[])
    assert out == init
