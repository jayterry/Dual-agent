"""llm_json 解析與修復。"""

from __future__ import annotations

import pytest

from dual_agent.llm_json import extract_json_object, invoke_and_parse_json


def test_extract_json_from_fence() -> None:
    raw = '```json\n{"task_type": "action", "task_state": "running", "todos": []}\n```'
    obj = extract_json_object(raw)
    assert obj["task_type"] == "action"


def test_extract_json_trailing_comma() -> None:
    raw = '{"complete": true, "final_answer": "ok", "updated_todos": [],}'
    obj = extract_json_object(raw)
    assert obj["complete"] is True


def test_extract_json_single_quotes_via_literal_eval() -> None:
    raw = "{'complete': True, 'final_answer': '測試', 'updated_todos': []}"
    obj = extract_json_object(raw)
    assert obj["final_answer"] == "測試"


def test_invoke_and_parse_json_retry() -> None:
    calls = ["not json", '{"complete": true, "final_answer": "x", "updated_todos": []}']

    def first() -> str:
        return calls[0]

    def retry() -> str:
        return calls[1]

    obj = invoke_and_parse_json(first, retry_invoke=retry)
    assert obj["complete"] is True


def test_extract_json_raises_on_empty() -> None:
    with pytest.raises(ValueError, match="空白"):
        extract_json_object("   ")
