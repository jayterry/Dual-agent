"""Memory / Context Layer：不依賴 Ollama 的單元測試。"""

from __future__ import annotations

from dual_agent.cai.context_layer import (
    SessionMemory,
    build_plan_summary,
    pack_context,
    record_turn,
)
from dual_agent.cai.schemas import PlanStep

import dual_agent.cai.context_layer as context_layer


def test_build_plan_summary_from_steps() -> None:
    p = build_plan_summary(
        [PlanStep(skill="search_web", args={"query": "測試"}), PlanStep(skill="ask_user", args={"question": "?"})]
    )
    assert "search_web" in p
    assert "ask_user" in p
    assert "測試" in p


def test_build_plan_summary_redacts_call_dai_context_pack() -> None:
    p = build_plan_summary(
        [
            PlanStep(
                skill="call_dai",
                args={
                    "artifact": "你男友在我手上，給我500萬",
                    "user_text": "請審查這則威脅訊息",
                    "context_pack": "【最近對話緩衝】很多很多內容",
                    "sms_review": True,
                },
            )
        ]
    )
    assert "call_dai" in p
    assert "請審查這則威脅訊息" in p
    assert "（已省略）" in p
    assert "很多很多內容" not in p


    s = SessionMemory()
    p = pack_context(s)
    assert "尚無累積脈絡" in p or "第一則" in p


def test_pack_includes_buffer_and_task() -> None:
    s = SessionMemory(
        rolling_summary="使用者喜歡繁中。",
        recent_buffer=[],
        task_snapshot={"task_type": "direct_response", "task_state": "answering"},
    )
    p = pack_context(s)
    assert "長期摘要" in p
    assert "任務狀態" in p
    assert "direct_response" in p


def test_pack_includes_plan_and_result_in_turn() -> None:
    s = SessionMemory()
    record_turn(
        s,
        user="搜尋 apex",
        assistant="（答覆略）",
        task_type="action",
        task_state="completed",
        model="m",
        base_url="http://127.0.0.1:11434",
        plan_summary="1. search_web {\"query\": \"Apex\"}",
        result_summary="[OK] search_web: 已開啟",
    )
    p = pack_context(s)
    assert "計畫摘要" in p
    assert "執行結果摘要" in p
    assert "search_web" in p
    assert "action" in p


def test_record_turn_overflow_uses_merge(monkeypatch) -> None:
    def fake_merge(existing: str, turn, **kwargs):  # noqa: ANN001
        return f"{existing}|{turn.user}"

    monkeypatch.setattr(context_layer, "context_buffer_max_rounds", lambda: 3)
    monkeypatch.setattr(context_layer, "merge_into_rolling_summary", fake_merge)

    s = SessionMemory()
    for i in range(4):
        record_turn(
            s,
            user=f"u{i}",
            assistant=f"a{i}",
            task_type="t",
            task_state="s",
            model="m",
            base_url="http://127.0.0.1:11434",
        )
    assert len(s.recent_buffer) == 3
    assert s.recent_buffer[-1].user == "u3"
    assert "u0" in s.rolling_summary
