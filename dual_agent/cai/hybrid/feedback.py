"""Hybrid 全局反饋：TurnTrace 與 thinking.entries（供 Mobile GET /pipeline）。"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.skill_types import SkillContext


class ThinkingEntry(BaseModel):
    kind: str
    label_zh: str = ""
    detail: dict[str, Any] | str = Field(default_factory=dict)


class TurnTrace(BaseModel):
    turn_id: str = ""
    primary_goal: str = ""
    message_features: dict[str, Any] | None = None
    planner_todos: list[dict[str, Any]] = Field(default_factory=list)
    react_trace: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)
    final_answer: str = ""


def _trace_dict(ctx: SkillContext) -> dict[str, Any]:
    raw = ctx.policy_state.get("turn_trace")
    if not isinstance(raw, dict):
        raw = {}
        ctx.policy_state["turn_trace"] = raw
    return raw


def init_turn_trace(ctx: SkillContext) -> TurnTrace:
    trace = TurnTrace(turn_id=str(uuid.uuid4()))
    ctx.policy_state["turn_trace"] = trace.model_dump()
    return trace


def record_message_features(ctx: SkillContext, features: MessageFeatures) -> None:
    raw = _trace_dict(ctx)
    raw["primary_goal"] = features.primary_goal
    raw["message_features"] = features.model_dump()
    from dual_agent.cai.pipeline_progress import _GOAL_THINKING, append_thinking

    rationale = (features.turn_intent.intent_rationale_zh or "").strip()
    conclusion = _GOAL_THINKING.get(features.primary_goal, "先理解這句話的意圖。")
    if rationale and rationale not in conclusion:
        spoken = f"{rationale.rstrip('。')}。因此{conclusion}"
    else:
        spoken = conclusion
    append_thinking(ctx, "nlp", "理解意圖", spoken)


def record_planner_todos(ctx: SkillContext, todos: list[Any], *, message: str = "") -> None:
    raw = _trace_dict(ctx)
    raw["planner_todos"] = [
        {"skill": s.skill, "args": dict(s.args or {})} for s in todos
    ]
    from dual_agent.cai.pipeline_progress import _SKILL_LABELS, append_thinking

    names: list[str] = []
    rationales: list[str] = []
    for step in todos:
        skill = str(getattr(step, "skill", "") or "").strip()
        if skill:
            names.append(_SKILL_LABELS.get(skill, skill))
        args = getattr(step, "args", None) or {}
        if isinstance(args, dict):
            why = str(args.get("rationale") or "").strip()
            if why:
                rationales.append(why)
    parts: list[str] = []
    msg = (message or "").strip()
    if msg and not msg.startswith("（") and "未經 Planner" not in msg:
        parts.append(msg[:280].rstrip("。") + "。")
    if rationales:
        parts.append(rationales[0][:200].rstrip("。") + "。")
    if names:
        parts.append("所以這輪要做：" + "、".join(names) + "。")
    if parts:
        append_thinking(ctx, "planner", "規劃", "".join(parts))


def append_observation(ctx: SkillContext, line: str) -> None:
    text = (line or "").strip()
    if not text:
        return
    raw = _trace_dict(ctx)
    obs = raw.setdefault("observations", [])
    if isinstance(obs, list):
        obs.append(text)


def sync_react_trace(ctx: SkillContext) -> None:
    raw = _trace_dict(ctx)
    react = ctx.policy_state.get("react_trace")
    if isinstance(react, list):
        raw["react_trace"] = list(react)


def finalize_turn_trace(ctx: SkillContext, *, final_answer: str = "") -> TurnTrace:
    raw = _trace_dict(ctx)
    sync_react_trace(ctx)
    if final_answer:
        raw["final_answer"] = final_answer.strip()
    trace = TurnTrace.model_validate(raw)
    ctx.policy_state["turn_trace"] = trace.model_dump()
    ctx.policy_state["turn_trace_last"] = trace.model_dump()
    return trace


def build_thinking_entries(ctx: SkillContext) -> list[dict[str, Any]]:
    """讀取 append-only thinking_log；不含 finish 總結。"""
    log = ctx.policy_state.get("thinking_log")
    if not isinstance(log, list):
        return []
    out: list[dict[str, Any]] = []
    for row in log:
        if not isinstance(row, dict):
            continue
        if str(row.get("kind") or "") == "finish":
            continue
        out.append(dict(row))
    return out


def snapshot_pipeline_for_ui(ctx: SkillContext, status: dict[str, Any]) -> None:
    """請求結束前保留最後一輪 pipeline + thinking 供 UI 輪詢。"""
    snap = dict(status)
    snap["thinking"] = {"entries": build_thinking_entries(ctx)}
    snap["snapshot_at"] = time.time()
    ctx.policy_state["pipeline_last"] = snap
