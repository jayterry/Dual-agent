"""
手機（USB + adb reverse）Dual-agent API。

  cd Dual-agent
  uvicorn mobile_server:app --host 127.0.0.1 --port 8787
  adb reverse tcp:8787 tcp:8787
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from dual_agent.cai.context_layer import (
    SessionMemory,
    build_plan_summary,
    merge_user_profile,
    pack_context,
    record_turn,
    record_turn_after_review,
)
from dual_agent.cai.executor import format_results_for_display
from dual_agent.cai.plan_execute import compose_review_user_text, run_dai_then_replan, run_plan_and_execute
from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.user_db import (
    list_trusted_domains,
    mark_blocked_domain,
    mark_trusted_domain,
    normalize_domain,
    remove_trusted_domain,
)
from dual_agent.skill_types import SkillContext

app = FastAPI(title="Dual-agent Mobile API", version="0.3.0")

_SESSION_TTL_SEC = max(60, int(os.environ.get("MOBILE_SESSION_TTL_SEC", "7200")))


@dataclass
class _SessionEntry:
    memory: SessionMemory = field(default_factory=SessionMemory)
    ctx: SkillContext = field(default_factory=lambda: SkillContext(user_input=""))
    touched_at: float = field(default_factory=time.time)


_SESSIONS: dict[str, _SessionEntry] = {}


class UserProfileBody(BaseModel):
    user_id: Optional[str] = None
    display_name: Optional[str] = None


def _require_token(authorization: Optional[str] = Header(default=None)) -> None:
    token = os.environ.get("AGENT_API_TOKEN")
    if not token:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="需要 Authorization: Bearer token")
    got = authorization[len("Bearer ") :].strip()
    if got != token:
        raise HTTPException(status_code=401, detail="token 不正確")


def _gc_sessions() -> None:
    now = time.time()
    dead = [sid for sid, e in _SESSIONS.items() if now - e.touched_at > _SESSION_TTL_SEC]
    for sid in dead[:200]:
        _SESSIONS.pop(sid, None)


def _get_session(session_id: str) -> _SessionEntry:
    _gc_sessions()
    sid = (session_id or "").strip() or str(uuid.uuid4())
    ent = _SESSIONS.get(sid)
    if ent is None:
        ent = _SessionEntry()
        _SESSIONS[sid] = ent
    ent.touched_at = time.time()
    return ent


def _profile_to_dict(profile: UserProfileBody | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    out: dict[str, Any] = {}
    if profile.user_id:
        out["user_id"] = profile.user_id.strip()
    if profile.display_name:
        out["display_name"] = profile.display_name.strip()
    return out or None


def _prepare_context(ent: _SessionEntry, profile: UserProfileBody | None) -> str:
    """merge user_profile、組 context_pack，並同步至 SkillContext.policy_state。"""
    pd = _profile_to_dict(profile)
    if pd:
        merge_user_profile(ent.memory, pd)
    cp = pack_context(ent.memory)
    ent.ctx.policy_state["context_pack"] = cp
    ent.ctx.policy_state["user_profile"] = dict(ent.memory.user_profile or {})
    ent.ctx.policy_state["task_snapshot"] = dict(ent.memory.task_snapshot or {})
    return cp


def _extract_dai_from_results(results: list[Any]) -> dict[str, Any] | None:
    for r in reversed(results):
        if getattr(r, "skill", "") != "call_dai":
            continue
        data = getattr(r, "data", {}) or {}
        dai = data.get("dai")
        if isinstance(dai, dict):
            return dai
    return None


def _extract_risk_user(dai: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dai:
        return None
    ru = dai.get("risk_user")
    return ru if isinstance(ru, dict) else None


def _build_memory_assistant_text(answer: str, results: list[Any]) -> str:
    base = (answer or "").strip()
    dai = _extract_dai_from_results(results)
    if not dai:
        return base
    lines = ["【DAI 風險摘要】"]
    score = dai.get("risk_score")
    if isinstance(score, (int, float)):
        lines.append(f"風險分數：{int(score)}/100")
    action = str(dai.get("recommended_cai_action") or "").strip()
    if action:
        lines.append(f"建議動作：{action}")
    summary = str(dai.get("safety_summary") or "").strip()
    if summary:
        lines.append(f"摘要：{summary[:300]}")
    reasons = dai.get("reason_highlights") or []
    if isinstance(reasons, list):
        picked = [str(x).strip()[:160] for x in reasons if str(x).strip()][:3]
        if picked:
            lines.append("主要原因：")
            lines.extend(f"- {x}" for x in picked)
    block = "\n".join(lines)
    if base and block:
        return f"{base}\n\n{block}"
    return base or block


def _outcome_to_response(session_id: str, out: Any) -> dict[str, Any]:
    dai = _extract_dai_from_results(list(out.results or []))
    risk_user = _extract_risk_user(dai)
    return {
        "session_id": session_id,
        "answer": (out.answer or "").strip(),
        "dai": dai,
        "risk_user": risk_user,
        "task_type": getattr(out, "task_type", ""),
        "task_state": getattr(out, "task_state", ""),
        "plan_steps": len(out.plan or []),
    }


class ReviewBody(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(default="請審查這則訊息是否有詐騙或資安風險")
    artifact: str = Field(..., min_length=1)
    input_origin: str = Field(default="sms_share")
    source: Optional[str] = None
    user_profile: Optional[UserProfileBody] = None


class ChatBody(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(..., min_length=1)
    artifact: Optional[str] = None
    input_origin: str = Field(default="chat_box")
    source: Optional[str] = None
    user_profile: Optional[UserProfileBody] = None


class DomainBody(BaseModel):
    domain: str = Field(..., min_length=1)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/review")
def review(body: ReviewBody, _: None = Depends(_require_token)) -> dict[str, Any]:
    sid = (body.session_id or "").strip() or str(uuid.uuid4())
    ent = _get_session(sid)
    if body.source:
        ent.ctx.policy_state["review_source"] = body.source.strip()

    context_pack = _prepare_context(ent, body.user_profile)
    out = run_dai_then_replan(
        message=body.message,
        artifact=body.artifact,
        ctx=ent.ctx,
        guard_source=body.input_origin,
        context_pack=context_pack,
    )

    memory_answer = _build_memory_assistant_text(out.answer, list(out.results or []))
    user_turn = compose_review_user_text(message=body.message, artifact=body.artifact)
    dai = _extract_dai_from_results(list(out.results or []))
    record_turn_after_review(
        ent.memory,
        user=user_turn,
        assistant=memory_answer,
        task_type=out.task_type,
        task_state=out.task_state,
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        plan_summary=build_plan_summary(out.plan),
        result_summary=format_results_for_display(out.results) if out.results else "",
        artifact=body.artifact,
        message_source=(body.source or ent.ctx.policy_state.get("review_source") or "unknown"),
        input_origin=body.input_origin,
        dai=dai,
    )
    ent.ctx.policy_state["task_snapshot"] = dict(ent.memory.task_snapshot or {})
    resp = _outcome_to_response(sid, out)
    resp["mode"] = "review_dai_replan"
    return resp


@app.post("/v1/chat")
def chat(body: ChatBody, _: None = Depends(_require_token)) -> dict[str, Any]:
    sid = (body.session_id or "").strip() or str(uuid.uuid4())
    ent = _get_session(sid)
    if body.source:
        ent.ctx.policy_state["review_source"] = body.source.strip()

    context_pack = _prepare_context(ent, body.user_profile)
    user_prompt = body.message.strip()
    artifact = (body.artifact or "").strip()
    guard_source = body.input_origin or ("sms_share" if artifact else "chat_box")

    out = run_plan_and_execute(
        user_text=user_prompt,
        artifact=artifact,
        ctx=ent.ctx,
        guard_source=guard_source,
        context_pack=context_pack,
    )

    memory_answer = _build_memory_assistant_text(out.answer, list(out.results or []))
    user_turn = compose_review_user_text(message=user_prompt, artifact=artifact) if artifact else user_prompt
    dai = _extract_dai_from_results(list(out.results or []))
    if dai:
        record_turn_after_review(
            ent.memory,
            user=user_turn,
            assistant=memory_answer,
            task_type=out.task_type,
            task_state=out.task_state,
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            plan_summary=build_plan_summary(out.plan),
            result_summary=format_results_for_display(out.results) if out.results else "",
            artifact=artifact or user_prompt,
            message_source=(body.source or ent.ctx.policy_state.get("review_source") or "unknown"),
            input_origin=guard_source,
            dai=dai,
        )
    else:
        record_turn(
            ent.memory,
            user=user_turn,
            assistant=memory_answer,
            task_type=out.task_type,
            task_state=out.task_state,
            model=OLLAMA_MODEL,
            base_url=OLLAMA_BASE_URL,
            plan_summary=build_plan_summary(out.plan),
            result_summary=format_results_for_display(out.results) if out.results else "",
        )
    ent.ctx.policy_state["task_snapshot"] = dict(ent.memory.task_snapshot or {})
    resp = _outcome_to_response(sid, out)
    resp["mode"] = "chat_plan_execute"
    return resp


@app.get("/v1/trust/domains")
def trust_domains_list(_: None = Depends(_require_token)) -> dict[str, Any]:
    return {"domains": list_trusted_domains()}


@app.post("/v1/trust/domains")
def trust_domains_add(body: DomainBody, _: None = Depends(_require_token)) -> dict[str, Any]:
    dom = normalize_domain(body.domain)
    if not dom:
        raise HTTPException(status_code=400, detail="無效網域")
    return mark_trusted_domain(domain=dom)


@app.delete("/v1/trust/domains")
def trust_domains_remove(body: DomainBody, _: None = Depends(_require_token)) -> dict[str, Any]:
    dom = normalize_domain(body.domain)
    if not dom:
        raise HTTPException(status_code=400, detail="無效網域")
    return remove_trusted_domain(domain=dom)


@app.post("/v1/trust/domains/block")
def trust_domains_block(body: DomainBody, _: None = Depends(_require_token)) -> dict[str, Any]:
    dom = normalize_domain(body.domain)
    if not dom:
        raise HTTPException(status_code=400, detail="無效網域")
    return mark_blocked_domain(domain=dom)
