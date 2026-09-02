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


def record_planner_todos(ctx: SkillContext, todos: list[Any]) -> None:
    raw = _trace_dict(ctx)
    raw["planner_todos"] = [
        {"skill": s.skill, "args": dict(s.args or {})} for s in todos
    ]


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


_GOAL_LABELS: dict[str, str] = {
    "review_sms": "送審簡訊",
    "ask_missing_body": "缺正文待補",
    "follow_up_review": "送審後追問",
    "remember_relation": "記住關係",
    "recall_relation": "回想關係",
    "out_of_scope": "超出範圍",
}


def build_thinking_entries(ctx: SkillContext) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    mf = ctx.policy_state.get("message_features")
    if isinstance(mf, dict) and mf:
        goal = str((mf.get("turn_intent") or {}).get("primary_goal") or "")
        entries.append(
            {
                "kind": "nlp",
                "label_zh": _GOAL_LABELS.get(goal, "理解意圖"),
                "detail": mf,
            }
        )
    trace = ctx.policy_state.get("turn_trace")
    if isinstance(trace, dict):
        todos = trace.get("planner_todos")
        if isinstance(todos, list) and todos:
            entries.append(
                {
                    "kind": "planner",
                    "label_zh": "規劃任務",
                    "detail": {"todos": todos},
                }
            )
        for obs in trace.get("observations") or []:
            if obs:
                entries.append(
                    {
                        "kind": "observation",
                        "label_zh": "執行結果",
                        "detail": {"text": str(obs)[:2000]},
                    }
                )
    react = ctx.policy_state.get("react_trace")
    if isinstance(react, list):
        for i, row in enumerate(react):
            if not isinstance(row, dict):
                continue
            thought = str(row.get("thought") or "").strip()
            entries.append(
                {
                    "kind": "react",
                    "label_zh": f"推理步驟 {i + 1}",
                    "detail": row,
                }
            )
    last = ctx.policy_state.get("turn_trace_last")
    if isinstance(last, dict) and last.get("final_answer"):
        entries.append(
            {
                "kind": "finish",
                "label_zh": "完成",
                "detail": {"final_answer": str(last.get("final_answer") or "")[:500]},
            }
        )
    return entries


def snapshot_pipeline_for_ui(ctx: SkillContext, status: dict[str, Any]) -> None:
    """請求結束前保留最後一輪 pipeline + thinking 供 UI 輪詢。"""
    snap = dict(status)
    snap["thinking"] = {"entries": build_thinking_entries(ctx)}
    snap["snapshot_at"] = time.time()
    ctx.policy_state["pipeline_last"] = snap
