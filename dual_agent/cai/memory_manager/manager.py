"""Memory Manager：把關、pending、user_facts 讀寫。"""

from __future__ import annotations

import json
from typing import Any, Callable

from dual_agent.cai.context_layer import (
    clear_relation_in_user_facts,
    format_relation_names,
    get_relation_names,
    normalize_relation,
    normalize_user_facts,
)
from dual_agent.cai.memory_direct import (
    _apply_confirmed_relation,
    _classify_memory_reply_llm,
    _clear_pending_memory,
    _format_recall_answer,
    _outcome,
    build_confirm_question,
    infer_relation_for_forget,
    is_affirmative_reply,
    is_deny_reply,
    looks_like_forget_memory_turn,
    try_recall_empty_relation,
    try_recall_from_user_facts,
)
from dual_agent.cai.memory_manager.llm import (
    invoke_memory_turn_llm,
    normalize_memory_decision,
    serialize_known_facts,
)
from dual_agent.cai.memory_manager.schemas import MemoryDecision
from dual_agent.cai.schemas import PlanExecuteOutcome
from dual_agent.config import cai_memory_model, memory_confidence_min
from dual_agent.skill_types import SkillContext


def _default_clarify_answer() -> str:
    return "請問您想讓我記住哪一個關係或名字？"


def _empty_recall_message(relation: str) -> str:
    rel = normalize_relation(relation)
    return f"目前尚未記錄您的{rel}。若要記住，請直接告訴我稱呼或名字。"


def _store_debug_decision(
    ctx: SkillContext,
    decision: MemoryDecision | None,
    *,
    model: str | None = None,
) -> None:
    if decision is None:
        ctx.policy_state.pop("last_memory_decision", None)
        return
    ctx.policy_state["last_memory_decision"] = {
        "intent": decision.intent,
        "relation": decision.relation,
        "value": decision.value,
        "mode": decision.mode,
        "confidence": decision.confidence,
        "reason": decision.reason,
        "model": model or "",
    }


def _handle_pending_confirm(
    user_text: str,
    *,
    ctx: SkillContext,
    pending: dict[str, Any],
    model: str,
    base_url: str,
    temperature: float,
    classify_fn: Callable[..., str] | None,
) -> PlanExecuteOutcome | None:
    relation = str(pending.get("relation") or "").strip()
    value = str(pending["value"])
    mode = str(pending.get("mode") or "set").strip().lower()
    if not relation and pending.get("fact_key"):
        relation = normalize_relation(str(pending["fact_key"]))
    if not relation:
        return None

    question = str(
        pending.get("question") or build_confirm_question(relation, value, mode=mode)
    )
    if is_affirmative_reply(user_text):
        intent = "affirm"
    elif is_deny_reply(user_text):
        intent = "deny"
    else:
        _classify = classify_fn or _classify_memory_reply_llm
        intent = _classify(
            user_text,
            pending_question=question,
            relation=relation,
            value=value,
            model=model,
            base_url=base_url,
            temperature=temperature,
        )
    if intent == "affirm":
        ctx.policy_state["user_facts"] = _apply_confirmed_relation(
            ctx.policy_state.get("user_facts"),
            relation,
            value,
            mode=mode,
        )
        _clear_pending_memory(ctx)
        ctx.policy_state.pop("pending_review", None)
        rel = normalize_relation(relation)
        names = get_relation_names(ctx.policy_state.get("user_facts"), rel)
        label = format_relation_names(names)
        if mode == "append" and len(names) > 1:
            return _outcome(
                f"好的，已記住。您的{rel}有 {label}。",
                task_state="completed",
            )
        return _outcome(
            f"好的，已記住您的{rel}是 {label}。",
            task_state="completed",
        )
    if intent == "deny":
        _clear_pending_memory(ctx)
        return _outcome(
            "了解，那我先不記這筆。請再告訴我正確的稱呼或關係。",
            task_state="waiting_input",
        )
    return None


def _start_pending_confirm(
    ctx: SkillContext,
    *,
    relation: str,
    value: str,
    mode: str,
    user_facts: dict[str, Any],
) -> PlanExecuteOutcome:
    rel = normalize_relation(relation)
    existing = get_relation_names(user_facts, rel) if mode == "append" else []
    question = build_confirm_question(
        rel,
        value,
        existing_names=existing,
        mode=mode,
    )
    ctx.policy_state["pending_memory_confirm"] = {
        "fact_type": "relation",
        "relation": rel,
        "value": value,
        "mode": mode,
        "question": question,
    }
    ctx.policy_state["pending_task"] = {
        "type": "ask_user",
        "question": question,
        "rationale": "確認使用者告知的關係事實後再寫入記憶",
        "expected_task": "direct_response",
    }
    ctx.policy_state["pending_user_question"] = question
    return _outcome(question, task_state="waiting_input")


def _handle_forget(
    user_text: str,
    *,
    ctx: SkillContext,
    uf: dict[str, Any],
) -> PlanExecuteOutcome | None:
    if not looks_like_forget_memory_turn(user_text):
        return None
    rel = infer_relation_for_forget(uf, user_text)
    relations_now: dict[str, list[str]] = dict(uf.get("relations") or {})
    if not rel and relations_now:
        if len(relations_now) == 1:
            rel = next(iter(relations_now))
        else:
            return _outcome(
                "請告訴我要忘記哪一種關係（例如專題組員、媽媽）。",
                task_state="waiting_input",
            )
    if rel:
        ctx.policy_state["user_facts"] = clear_relation_in_user_facts(
            ctx.policy_state.get("user_facts"),
            rel,
        )
        _clear_pending_memory(ctx)
        ctx.policy_state.pop("pending_review", None)
        rel_label = normalize_relation(rel)
        return _outcome(
            f"好的，已忘記您先前記錄的{rel_label}。若要記住新的成員，請直接告訴我名字。",
            task_state="completed",
        )
    return _outcome(
        "目前沒有已記錄的人際關係可忘記。",
        task_state="completed",
    )


def _handle_recall(
    decision: MemoryDecision,
    *,
    uf: dict[str, Any],
) -> str | None:
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    rel = normalize_relation(decision.relation or decision.raw_relation)
    if decision.answer and decision.answer.strip():
        return decision.answer.strip()
    if rel:
        names = list(relations.get(rel) or [])
        if names:
            return _format_recall_answer(rel, names)
        return _empty_recall_message(rel)
    if len(relations) == 1:
        only_rel = next(iter(relations))
        names = relations[only_rel]
        if names:
            return _format_recall_answer(only_rel, names)
    return None


def _validate_remember(
    decision: MemoryDecision,
    uf: dict[str, Any],
) -> tuple[str, str, str] | None:
    """回傳 (relation, value, mode) 或 None 表示應 clarify。"""
    rel = normalize_relation(decision.relation or decision.raw_relation)
    val = (decision.value or decision.raw_value or "").strip()
    mode = decision.mode or (
        "append" if decision.intent == "remember_append" else "set"
    )
    if mode not in ("set", "append"):
        mode = "set" if decision.intent == "remember_set" else "append"
    if not rel or not val:
        return None
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if decision.intent == "remember_append" and rel not in relations:
        return None
    return rel, val, mode


def _parse_fn_to_memory_llm(
    parse_fn: Callable[..., dict[str, Any] | None],
) -> Callable[..., MemoryDecision | None]:
    """舊測試 parse_fn 相容層。"""

    def _adapter(
        user_text: str,
        known_facts_json: str,
        context_pack: str | None = None,
        **kwargs: Any,
    ) -> MemoryDecision | None:
        uf = normalize_user_facts(
            {"relations": json.loads(known_facts_json or "{}")}
        )
        parsed = parse_fn(
            user_text,
            user_facts=uf,
            model=kwargs.get("model", ""),
            base_url=kwargs.get("base_url", ""),
            temperature=kwargs.get("temperature", 0.2),
        )
        if not parsed or parsed.get("fact_type") != "relation":
            return MemoryDecision(intent="none", confidence=0.0, reason="parse_fn_miss")
        mode = str(parsed.get("mode") or "set").strip().lower()
        intent = "remember_append" if mode == "append" else "remember_set"
        return MemoryDecision(
            intent=intent,
            relation=str(parsed.get("relation") or ""),
            value=str(parsed.get("value") or ""),
            mode=mode if mode in ("set", "append") else "set",
            confidence=0.9,
            reason="parse_fn_adapter",
        )

    return _adapter


def handle_memory_turn(
    user_text: str,
    *,
    ctx: SkillContext,
    user_facts: dict[str, Any] | None,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    memory_llm_fn: Callable[..., MemoryDecision | None] | None = None,
    parse_fn: Any = None,
    classify_fn: Any = None,
    context_pack: str | None = None,
) -> PlanExecuteOutcome | None:
    from dual_agent.config import OLLAMA_BASE_URL

    mem_model = model or cai_memory_model()
    mem_base = base_url or OLLAMA_BASE_URL

    uf = normalize_user_facts(user_facts)
    if not isinstance(ctx.policy_state.get("user_facts"), dict):
        ctx.policy_state["user_facts"] = normalize_user_facts(uf)
    else:
        uf = normalize_user_facts(ctx.policy_state.get("user_facts"))

    pending = ctx.policy_state.get("pending_memory_confirm")
    if isinstance(pending, dict) and pending.get("value"):
        return _handle_pending_confirm(
            user_text,
            ctx=ctx,
            pending=pending,
            model=mem_model,
            base_url=mem_base,
            temperature=temperature,
            classify_fn=classify_fn,
        )

    _llm = memory_llm_fn
    if _llm is None and parse_fn is not None:
        _llm = _parse_fn_to_memory_llm(parse_fn)
    if _llm is None:
        _llm = invoke_memory_turn_llm

    known_json = serialize_known_facts(uf)
    decision = _llm(
        user_text,
        known_json,
        context_pack,
        model=mem_model,
        base_url=mem_base,
        temperature=temperature,
    )
    _store_debug_decision(ctx, decision, model=mem_model)

    if decision is None:
        forget_out = _handle_forget(user_text, ctx=ctx, uf=uf)
        if forget_out is not None:
            return forget_out
        empty_recall = try_recall_empty_relation(user_text, uf)
        if empty_recall:
            ctx.policy_state.pop("pending_review", None)
            return _outcome(empty_recall, task_state="completed")
        recalled = try_recall_from_user_facts(user_text, uf)
        if recalled:
            ctx.policy_state.pop("pending_review", None)
            return _outcome(recalled, task_state="completed")
        return None

    decision = normalize_memory_decision(decision)
    _store_debug_decision(ctx, decision, model=mem_model)

    if decision.intent == "none":
        forget_out = _handle_forget(user_text, ctx=ctx, uf=uf)
        if forget_out is not None:
            return forget_out
        empty_recall = try_recall_empty_relation(user_text, uf)
        if empty_recall:
            ctx.policy_state.pop("pending_review", None)
            return _outcome(empty_recall, task_state="completed")
        recalled = try_recall_from_user_facts(user_text, uf)
        if recalled:
            ctx.policy_state.pop("pending_review", None)
            return _outcome(recalled, task_state="completed")
        return None

    if decision.intent == "forget":
        rel = normalize_relation(decision.relation or decision.raw_relation)
        if not rel:
            return _handle_forget(user_text, ctx=ctx, uf=uf)
        ctx.policy_state["user_facts"] = clear_relation_in_user_facts(
            ctx.policy_state.get("user_facts"),
            rel,
        )
        _clear_pending_memory(ctx)
        ctx.policy_state.pop("pending_review", None)
        return _outcome(
            f"好的，已忘記您先前記錄的{normalize_relation(rel)}。若要記住新的成員，請直接告訴我名字。",
            task_state="completed",
        )

    if decision.intent == "recall":
        ans = _handle_recall(decision, uf=uf)
        if not ans:
            empty_recall = try_recall_empty_relation(user_text, uf)
            if empty_recall:
                ans = empty_recall
            else:
                recalled = try_recall_from_user_facts(user_text, uf)
                ans = recalled
        if ans:
            ctx.policy_state.pop("pending_review", None)
            return _outcome(ans, task_state="completed")
        return None

    if decision.intent == "clarify":
        msg = (decision.answer or "").strip() or _default_clarify_answer()
        return _outcome(msg, task_state="waiting_input")

    if decision.intent in ("remember_set", "remember_append"):
        if decision.confidence < memory_confidence_min():
            msg = (decision.answer or "").strip() or _default_clarify_answer()
            return _outcome(msg, task_state="waiting_input")
        validated = _validate_remember(decision, uf)
        if not validated:
            msg = (decision.answer or "").strip() or _default_clarify_answer()
            return _outcome(msg, task_state="waiting_input")
        rel, val, mode = validated
        return _start_pending_confirm(
            ctx,
            relation=rel,
            value=val,
            mode=mode,
            user_facts=uf,
        )

    return None
