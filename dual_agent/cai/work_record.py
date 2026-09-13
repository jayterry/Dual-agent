"""工作紀錄：精確進度與本輪關係（與對話摘要分離）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

WorkStatus = str  # active | waiting | paused | completed | cancelled
TurnRelation = str  # continue | clarify | correct | aside | switch | cancel

WORK_STATUSES = frozenset({"active", "waiting", "paused", "completed", "cancelled"})
TURN_RELATIONS = frozenset({"continue", "clarify", "correct", "aside", "switch", "cancel"})

# 切換工作時應重設的「工作專屬」欄位（保留 task_type 等可由呼叫端再寫）
_REVIEW_OWNED_KEYS = frozenset(
    {
        "review_phase",
        "has_dai_result",
        "artifact_key",
        "artifact_excerpt",
        "last_risk_score",
        "last_safety_summary",
        "last_recommended_action",
        "message_source",
        "input_origin",
        "review_request_id",
    }
)

_WORK_CORE_KEYS = frozenset(
    {
        "work_id",
        "goal",
        "status",
        "current_step",
        "next_action",
        "constraints",
        "waiting_for",
        "last_question",
        "completed",
        "turn_relation",
        "last_error",
        "updated_at",
        "review_request_id",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_work_id(prefix: str = "review") -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def default_work_record(
    *,
    work_id: str | None = None,
    goal: str = "審查可疑簡訊風險",
    status: str = "waiting",
) -> dict[str, Any]:
    return {
        "work_id": work_id or new_work_id(),
        "goal": goal,
        "status": status,
        "current_step": "",
        "next_action": "",
        "constraints": [],
        "waiting_for": None,
        "last_question": None,
        "completed": [],
        "turn_relation": "continue",
        "last_error": None,
        "updated_at": _now_iso(),
    }


def merge_work_record(snapshot: dict[str, Any] | None, **fields: Any) -> dict[str, Any]:
    """合併工作欄位；不刪除既有 review／task 欄。可傳 None 以清空 waiting_for 等。"""
    snap = dict(snapshot or {})
    snap.update(fields)
    snap["updated_at"] = _now_iso()
    return snap


def start_work(
    *,
    goal: str = "審查可疑簡訊風險",
    status: str = "waiting",
    keep_background: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    開新工作：新 work_id，重設工作／審查專屬欄位。
    keep_background 可帶入非工作專屬欄（例如 task_type），不會帶回舊 artifact／風險摘要。
    """
    base = default_work_record(goal=goal, status=status)
    bg = dict(keep_background or {})
    for key in list(bg.keys()):
        if key in _WORK_CORE_KEYS or key in _REVIEW_OWNED_KEYS:
            bg.pop(key, None)
    out = {**bg, **base}
    out["turn_relation"] = "switch"
    return out


def on_waiting_for_body(
    snapshot: dict[str, Any] | None,
    *,
    question: str,
    turn_relation: str = "continue",
) -> dict[str, Any]:
    snap = dict(snapshot or {})
    if not str(snap.get("work_id") or "").strip():
        snap = {**default_work_record(status="waiting"), **snap}
    return merge_work_record(
        snap,
        status="waiting",
        waiting_for="reviewable_body",
        last_question=question,
        current_step="等待使用者提供完整簡訊正文",
        next_action="正文完整且本輪意圖允許送審後呼叫 call_dai",
        constraints=[
            "需完整簡訊正文",
            "不得以網路搜尋代替使用者提供的正文",
        ],
        turn_relation=turn_relation,
        last_error=None,
        goal=str(snap.get("goal") or "審查可疑簡訊風險"),
    )


def on_body_ready(
    snapshot: dict[str, Any] | None,
    *,
    turn_relation: str = "continue",
    review_request_id: str | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "status": "active",
        "waiting_for": None,
        "current_step": "準備送審可疑簡訊",
        "next_action": "本輪意圖允許時呼叫 call_dai",
        "turn_relation": turn_relation,
        "last_error": None,
    }
    if review_request_id:
        fields["review_request_id"] = review_request_id
    return merge_work_record(snapshot, **fields)


def on_dai_success(
    snapshot: dict[str, Any] | None,
    *,
    dai: dict[str, Any] | None = None,
    artifact: str = "",
    message_source: str = "",
    input_origin: str = "",
    turn_relation: str = "continue",
) -> dict[str, Any]:
    from dual_agent.cai.context_layer import _norm_artifact_key, _truncate

    dai_payload = dict(dai or {})
    snap = dict(snapshot or {})
    completed = list(snap.get("completed") or [])
    step = "call_dai"
    if step not in completed:
        completed.append(step)
    fields: dict[str, Any] = {
        "status": "completed",
        "waiting_for": None,
        "current_step": "已完成風險審查",
        "next_action": "若使用者追問結果則依既有摘要回答",
        "completed": completed,
        "turn_relation": turn_relation,
        "last_error": None,
        "review_phase": "review_completed",
        "has_dai_result": True,
        "message_source": (message_source or "").strip() or str(snap.get("message_source") or "unknown"),
        "input_origin": (input_origin or "").strip() or str(snap.get("input_origin") or "unknown"),
        "artifact_key": _norm_artifact_key(artifact),
        "artifact_excerpt": _truncate((artifact or "").strip(), 400),
    }
    score = dai_payload.get("risk_score")
    if isinstance(score, (int, float)):
        fields["last_risk_score"] = int(score)
    summ = str(dai_payload.get("safety_summary") or "").strip()
    if summ:
        fields["last_safety_summary"] = _truncate(summ, 500)
    action = str(dai_payload.get("recommended_cai_action") or "").strip()
    if action:
        fields["last_recommended_action"] = action
    if not str(snap.get("work_id") or "").strip():
        snap = {**default_work_record(status="completed"), **snap}
    return merge_work_record(snap, **fields)


def on_dai_failure(
    snapshot: dict[str, Any] | None,
    *,
    error: str,
    turn_relation: str = "continue",
) -> dict[str, Any]:
    return merge_work_record(
        snapshot,
        status="active",
        current_step="送審未成功",
        next_action="確認正文後可再試 call_dai，或請使用者補充",
        last_error=(error or "").strip() or "dai_failed",
        turn_relation=turn_relation,
        has_dai_result=False,
    )


def on_aside(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """插問：只改 turn_relation，不改進度。"""
    snap = dict(snapshot or {})
    if not snap:
        return {}
    return merge_work_record(snap, turn_relation="aside")


def on_pause(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return merge_work_record(
        snapshot,
        status="paused",
        next_action="使用者恢復後再依既有進度繼續",
        turn_relation="continue",
    )


def on_cancel(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return merge_work_record(
        snapshot,
        status="cancelled",
        waiting_for=None,
        current_step="使用者已取消",
        next_action="",
        turn_relation="cancel",
    )


def on_follow_up(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snap = dict(snapshot or {})
    if not snap:
        return {}
    return merge_work_record(snap, turn_relation="continue")


def apply_turn_relation(snapshot: dict[str, Any] | None, relation: str) -> dict[str, Any]:
    rel = (relation or "").strip().lower()
    if rel not in TURN_RELATIONS:
        rel = "continue"
    snap = dict(snapshot or {})
    if not snap:
        return {}
    if rel == "aside":
        return on_aside(snap)
    if rel == "cancel":
        return on_cancel(snap)
    return merge_work_record(snap, turn_relation=rel)


def work_id_matches(snapshot: dict[str, Any] | None, work_id: str | None) -> bool:
    if not work_id:
        return True
    current = str((snapshot or {}).get("work_id") or "").strip()
    return bool(current) and current == str(work_id).strip()


def is_work_open(snapshot: dict[str, Any] | None) -> bool:
    status = str((snapshot or {}).get("status") or "").strip().lower()
    return status in {"active", "waiting", "paused"}


def format_work_record_for_prompt(snapshot: dict[str, Any] | None) -> str:
    """給 NLP／Planner 的精簡工作紀錄（繁中）。"""
    snap = dict(snapshot or {})
    if not snap or not str(snap.get("work_id") or "").strip():
        # 仍可能只有舊版 review 欄
        if not snap:
            return ""
    lines: list[str] = []
    wid = str(snap.get("work_id") or "").strip()
    if wid:
        lines.append(f"work_id：{wid}")
    goal = str(snap.get("goal") or "").strip()
    if goal:
        lines.append(f"目標：{goal}")
    status = str(snap.get("status") or "").strip()
    if status:
        lines.append(f"狀態：{status}")
    step = str(snap.get("current_step") or "").strip()
    if step:
        lines.append(f"目前步驟：{step}")
    nxt = str(snap.get("next_action") or "").strip()
    if nxt:
        lines.append(f"下一步（待辦描述，非執行授權）：{nxt}")
    waiting = snap.get("waiting_for")
    if waiting:
        lines.append(f"等待：{waiting}")
    lq = str(snap.get("last_question") or "").strip()
    if lq:
        lines.append(f"上一輪問題：{lq}")
    cons = snap.get("constraints")
    if isinstance(cons, list) and cons:
        lines.append("約束：" + "；".join(str(c) for c in cons if str(c).strip()))
    completed = snap.get("completed")
    if isinstance(completed, list) and completed:
        lines.append("已完成：" + "、".join(str(c) for c in completed if str(c).strip()))
    rel = str(snap.get("turn_relation") or "").strip()
    if rel:
        lines.append(f"上一輪關係標記（僅供參考，本輪須重判）：{rel}")
    err = str(snap.get("last_error") or "").strip()
    if err:
        lines.append(f"上次錯誤：{err}")
    return "\n".join(lines)


def sync_snapshot_to_ctx(ctx: Any, snapshot: dict[str, Any] | None) -> None:
    """寫入 SkillContext.policy_state['task_snapshot']。"""
    if ctx is None:
        return
    ps = getattr(ctx, "policy_state", None)
    if not isinstance(ps, dict):
        return
    ps["task_snapshot"] = dict(snapshot or {})
