"""task_taxonomy：task_type 正規化。"""

from __future__ import annotations

from dual_agent.cai.task_taxonomy import normalize_task_type


def test_normalize_general_qa_alias() -> None:
    assert normalize_task_type("general_qa") == "direct_response"


def test_normalize_no_tool_response_alias() -> None:
    assert normalize_task_type("no_tool_response") == "direct_response"


def test_normalize_passthrough() -> None:
    assert normalize_task_type("action") == "action"
    assert normalize_task_type("check") == "check"


def test_normalize_unknown() -> None:
    assert normalize_task_type("chatty_mc_chatface") == "unknown"
