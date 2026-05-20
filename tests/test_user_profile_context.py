"""user_profile 併入長期記憶與 task_snapshot。"""

from __future__ import annotations

from dual_agent.cai.context_layer import (
    SessionMemory,
    format_long_term_memory_block,
    merge_user_profile,
    pack_context,
    record_turn_after_review,
)


def test_long_term_memory_includes_profile_and_summary() -> None:
    mem = SessionMemory()
    merge_user_profile(mem, {"user_id": "u1", "display_name": "Alex"})
    mem.rolling_summary = "使用者曾討論貸款簡訊。"
    block = format_long_term_memory_block(mem)
    assert "display_name=Alex" in block
    assert "使用者曾討論貸款" in block
    packed = pack_context(mem)
    assert "【長期記憶】" in packed
    assert "【上一輪送審工作狀態】" not in packed


def test_record_turn_after_review_sets_task_snapshot() -> None:
    mem = SessionMemory()
    merge_user_profile(mem, {"display_name": "Alex"})
    snap = record_turn_after_review(
        mem,
        user="審查",
        assistant="風險 45",
        task_type="check",
        task_state="completed",
        model="fake",
        base_url="http://127.0.0.1",
        artifact="貸款廣告簡訊",
        message_source="0961592321",
        dai={"risk_score": 45, "safety_summary": "疑似貸款"},
    )
    assert snap["review_phase"] == "review_completed"
    assert mem.task_snapshot.get("last_risk_score") == 45
    assert len(mem.recent_buffer) == 1
