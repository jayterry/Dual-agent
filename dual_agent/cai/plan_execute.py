"""
CAI 主迴路（嚴格依流程圖）：

User（+ 上下文占位）→ Planner LLM →
  - Todo 為空 → Replan LLM（不經 Executor）→ 最終回答／等待輸入
  - Todo 非空 → Executor 僅執行 Todo[0] → Replan LLM → …（直到完成或達上限）

不含：獨立意圖分類器、policy_gate、nl_router、chat_responder 平行路徑。
"""

from __future__ import annotations

import json
from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL, max_executor_steps, max_replan_iterations
from dual_agent.cai.executor import execute_step, format_results_for_display
from dual_agent.cai.planner_llm import invoke_planner
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.replan_llm import invoke_replan
from dual_agent.cai.schemas import PlanExecuteOutcome, PlanStep, ReplanOutput
from dual_agent.ingress import (
    DetectedTaskType,
    IngressPayload,
    InputRole,
    ReviewScope,
    format_ingress_for_prompt,
    ingress_payload_to_dict,
    normalize_ingress,
)
from dual_agent.skill_types import SkillContext, SkillResult
from dual_agent.skills_registry import get_tool_catalog, parse_inline_skill_calls, strip_inline_skill_calls

_REVIEW_ASK_USER_QUESTION = "請貼上完整簡訊或訊息內容，我才能幫您審查風險。"
_REVIEW_ASK_USER_ANSWER = (
    "請貼上完整簡訊或訊息內容，我才能幫您進一步審查。"
    "若您本人或家人有立即危險，請先聯絡警方或當地緊急單位。"
)


def _out_plan(initial: list[PlanStep], executed: list[PlanStep]) -> list[PlanStep]:
    """回傳給 UI 的 plan：有實際執行過則以執行序為準，否則用 Planner 初始佇列。"""
    return list(executed) if executed else list(initial)


def _planner_payload(user_text: str, ctx: SkillContext) -> str:
    """組 Planner 輸入：接續上一輪 ask_user、合併使用者明確 skill 語法。"""
    prefix = ""
    pending = ctx.policy_state.get("pending_task")
    if isinstance(pending, dict) and str(pending.get("type") or "").strip().lower() == "ask_user":
        q = str(pending.get("question") or "").strip()
        ctx.policy_state.pop("pending_task", None)
        ctx.policy_state.pop("pending_user_question", None)
        if q:
            prefix = f"【接續上一輪】先前問題：{q}\n\n"

    explicit = list(parse_inline_skill_calls(user_text))
    stripped = strip_inline_skill_calls(user_text).strip()
    body = stripped if stripped else user_text.strip()
    parts: list[str] = [prefix + body]
    if explicit:
        parts.append("\n【使用者已指定 skill 步驟（請放在 todos 最前面，順序一致）】")
        for name, args in explicit:
            parts.append(json.dumps({"skill": name, "args": dict(args)}, ensure_ascii=False))
    return "\n".join(parts)


def _task_snapshot_from_ctx(ctx: SkillContext) -> dict[str, Any] | None:
    snap = ctx.policy_state.get("task_snapshot")
    return snap if isinstance(snap, dict) else None


def _planner_source_turn_text(user_text: str, ingress: IngressPayload) -> str:
    """
    給 Planner / Replan 的任務主鍵。

    - 若 ingress 已抽出 intent_text，優先使用 intent_text
    - 否則回退到原始輸入
    """
    intent = (ingress.intent_text or "").strip()
    if intent:
        return intent
    return user_text.strip()


def _review_ask_user_step() -> PlanStep:
    return PlanStep(
        skill="ask_user",
        args={
            "question": _REVIEW_ASK_USER_QUESTION,
            "rationale": "需要待審內容才能進行威脅或詐騙風險審查",
            "expected_task": "check",
        },
    )


def _set_pending_review(ctx: SkillContext, ingress: IngressPayload) -> None:
    ctx.policy_state["pending_review"] = {
        "active": True,
        "source_turn": ingress.raw_input_text,
        "input_origin": str(ingress.input_origin),
    }
    ctx.policy_state["pending_task"] = {
        "type": "ask_user",
        "question": _REVIEW_ASK_USER_QUESTION,
        "rationale": "需要待審內容才能進行威脅或詐騙風險審查",
        "expected_task": "check",
    }
    ctx.policy_state["pending_user_question"] = _REVIEW_ASK_USER_QUESTION


def _clear_pending_review(ctx: SkillContext) -> None:
    ctx.policy_state.pop("pending_review", None)


def _direct_review_ask_user(ctx: SkillContext, ingress: IngressPayload) -> PlanExecuteOutcome:
    _set_pending_review(ctx, ingress)
    step = _review_ask_user_step()
    return PlanExecuteOutcome(
        plan=[step],
        results=[],
        answer=_REVIEW_ASK_USER_ANSWER,
        task_type="check",
        task_state="waiting_input",
    )


def _pending_review_should_promote_raw_input(ingress: IngressPayload) -> bool:
    """僅對明確標記之威脅候補自動把本輪原句晉升为 artifact（其餘交 Planner／validate）。"""
    return bool((ingress.metadata or {}).get("threat_review_candidate"))


def _coerce_pending_review_artifact(ingress: IngressPayload) -> IngressPayload:
    ingress.input_role = InputRole.ARTIFACT
    ingress.artifact_text = ingress.raw_input_text
    ingress.detected_task_type = DetectedTaskType.CHECK
    ingress.requires_dai = True
    ingress.safety_relevant = True
    ingress.review_scope = ReviewScope.RAW_INPUT
    ingress.metadata["pending_review_artifact"] = True
    return ingress


def compose_review_user_text(*, message: str, artifact: str) -> str:
    msg = (message or "").strip()
    art = (artifact or "").strip()
    if art and msg:
        return f"{msg}\n\n【待審內容】\n{art}"
    return art or msg


def _direct_review_call_dai_plan(ingress: IngressPayload, context_pack: str | None) -> tuple[list[PlanStep], str, str]:
    step = PlanStep(
        skill="call_dai",
        args={
            "artifact": ingress.artifact_text,
            "user_text": ingress.intent_text or "請審查這則威脅訊息",
            "context_pack": (context_pack or "").strip(),
            "sms_review": True,
        },
    )
    return [step], "check", "running"


def _run_replan_loop(
    *,
    normalized_turn: str,
    task_type: str,
    task_state: str,
    initial_plan: list[PlanStep],
    todos: list[PlanStep],
    po_message: str,
    ctx: SkillContext,
    results: list[SkillResult],
    executed_trace: list[PlanStep],
    model: str,
    base_url: str,
    temperature: float,
    context_pack: str | None,
    active_pending_review: bool,
) -> PlanExecuteOutcome:
    observation_lines: list[str] = []
    observation_log: str | None = None
    cap = max_replan_iterations()
    exec_cap = max_executor_steps()
    replan_count = 0
    last_ro: ReplanOutput | None = None
    while replan_count < cap:
        if todos:
            if len(results) >= exec_cap:
                observation_log = "\n\n".join(observation_lines) if observation_lines else "（無）"
                suffix = (
                    f"\n\n【系統】本回合已執行 {exec_cap} 次工具，不得再執行。"
                    "請設 complete=true，用 final_answer 依上方紀錄總結回答使用者；updated_todos=[]。"
                )
                ro = invoke_replan(
                    user_text=normalized_turn,
                    task_type=task_type,
                    task_state=task_state,
                    remaining_todos=[],
                    observation_log=(observation_log or "（無）") + suffix,
                    planner_message=po_message,
                    model=model,
                    base_url=base_url,
                    temperature=temperature,
                    context_pack=context_pack,
                    pending_review=active_pending_review,
                )
                last_ro = ro
                replan_count += 1
                task_state = ro.task_state
                if ro.waiting_input:
                    ctx.policy_state["pending_task"] = {
                        "type": "ask_user",
                        "question": (ro.user_prompt or "請補充資訊。").strip(),
                    }
                    return PlanExecuteOutcome(
                        plan=_out_plan(initial_plan, executed_trace),
                        results=results,
                        answer=(ro.user_prompt or "請補充資訊。").strip(),
                        task_type=task_type,
                        task_state=ro.task_state,
                    )
                if ro.complete or (ro.final_answer or "").strip():
                    return PlanExecuteOutcome(
                        plan=_out_plan(initial_plan, executed_trace),
                        results=results,
                        answer=ro.final_answer or "（完成）",
                        task_type=task_type,
                        task_state=ro.task_state,
                    )
                return PlanExecuteOutcome(
                    plan=_out_plan(initial_plan, executed_trace),
                    results=results,
                    answer=(ro.final_answer or "").strip()
                    or "（已達工具執行上限，且 Replan 未產生總結。）",
                    task_type=task_type,
                    task_state=ro.task_state,
                )

            st = todos[0]
            executed_trace.append(PlanStep(skill=st.skill, args=dict(st.args)))
            r = execute_step(st, ctx)
            results.append(r)
            observation_lines.append(
                f"--- 第 {len(observation_lines) + 1} 次執行：{st.skill} ---\n"
                + format_results_for_display([r])
            )
            observation_log = "\n\n".join(observation_lines)
            todos = todos[1:]

        ro = invoke_replan(
            user_text=normalized_turn,
            task_type=task_type,
            task_state=task_state,
            remaining_todos=todos,
            observation_log=observation_log,
            planner_message=po_message,
            model=model,
            base_url=base_url,
            temperature=temperature,
            context_pack=context_pack,
            pending_review=active_pending_review,
        )
        last_ro = ro
        replan_count += 1
        task_state = ro.task_state

        if ro.waiting_input:
            ctx.policy_state["pending_task"] = {
                "type": "ask_user",
                "question": (ro.user_prompt or "請補充資訊。").strip(),
            }
            return PlanExecuteOutcome(
                plan=_out_plan(initial_plan, executed_trace),
                results=results,
                answer=(ro.user_prompt or "請補充資訊。").strip(),
                task_type=task_type,
                task_state=ro.task_state,
            )

        if ro.complete:
            return PlanExecuteOutcome(
                plan=_out_plan(initial_plan, executed_trace),
                results=results,
                answer=ro.final_answer or "（完成）",
                task_type=task_type,
                task_state=ro.task_state,
            )

        todos = list(ro.updated_todos)
        if not todos:
            fa = (ro.final_answer or "").strip()
            if fa:
                return PlanExecuteOutcome(
                    plan=_out_plan(initial_plan, executed_trace),
                    results=results,
                    answer=fa,
                    task_type=task_type,
                    task_state=ro.task_state,
                )
            return PlanExecuteOutcome(
                plan=_out_plan(initial_plan, executed_trace),
                results=results,
                answer="（已停止：待辦已空但 Replan 未標記完成。）",
                task_type=task_type,
                task_state=ro.task_state,
            )

    return PlanExecuteOutcome(
        plan=_out_plan(initial_plan, executed_trace),
        results=results,
        answer=(
            (last_ro.final_answer or "").strip()
            if last_ro and (last_ro.final_answer or "").strip()
            else "（已達 MAX_REPLAN_ITERATIONS，已停止。）"
        ),
        task_type=task_type,
        task_state=task_state,
    )


def run_dai_then_replan(
    *,
    message: str,
    artifact: str,
    model: str = OLLAMA_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.2,
    ctx: SkillContext | None = None,
    guard_source: str | None = None,
    context_pack: str | None = None,
) -> PlanExecuteOutcome:
    """
    手機送審專用：跳過 Planner，固定 call_dai → Replan（仍寫入同一 SkillContext / session）。
    """
    art = (artifact or "").strip()
    user_text = compose_review_user_text(message=message, artifact=artifact)
    ctx = ctx or SkillContext(user_input=user_text)
    ctx.user_input = user_text
    if context_pack:
        ctx.policy_state["context_pack"] = (context_pack or "").strip()
    if guard_source:
        ctx.policy_state["review_source"] = guard_source

    ingress = normalize_ingress(raw_input_text=user_text, input_origin=guard_source or "sms_share")
    if art and not (ingress.artifact_text or "").strip():
        ingress.artifact_text = art
        ingress.detected_task_type = DetectedTaskType.CHECK
        ingress.requires_dai = True
        ingress.safety_relevant = True
        ingress.review_scope = ReviewScope.ARTIFACT_ONLY
    ctx.policy_state["ingress_payload"] = ingress_payload_to_dict(ingress)

    if not art:
        return _direct_review_ask_user(ctx, ingress)

    _clear_pending_review(ctx)
    normalized_turn = _planner_source_turn_text(user_text, ingress)
    initial_plan, task_type, task_state = _direct_review_call_dai_plan(ingress, context_pack)
    po_message = "（送審：DAI call_dai 後由 Replan 總結；未經 Planner）"

    results: list[SkillResult] = []
    executed_trace: list[PlanStep] = []
    todos = list(initial_plan)

    return _run_replan_loop(
        normalized_turn=normalized_turn,
        task_type=task_type,
        task_state=task_state,
        initial_plan=initial_plan,
        todos=todos,
        po_message=po_message,
        ctx=ctx,
        results=results,
        executed_trace=executed_trace,
        model=model,
        base_url=base_url,
        temperature=temperature,
        context_pack=context_pack,
        active_pending_review=False,
    )


def _build_ingress_for_turn(
    *,
    user_text: str,
    artifact: str,
    guard_source: str,
) -> IngressPayload:
    """合併聊天框 user prompt 與可選 artifact，供 ingress 解析。"""
    msg = (user_text or "").strip()
    art = (artifact or "").strip()
    combined = compose_review_user_text(message=msg, artifact=art) if art else msg
    ingress = normalize_ingress(raw_input_text=combined, input_origin=guard_source)
    if art and not (ingress.artifact_text or "").strip():
        ingress.artifact_text = art
        ingress.detected_task_type = DetectedTaskType.CHECK
        ingress.requires_dai = True
        ingress.safety_relevant = True
        ingress.review_scope = ReviewScope.ARTIFACT_ONLY
    return ingress


def run_plan_and_execute(
    *,
    user_text: str,
    artifact: str = "",
    model: str = OLLAMA_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.2,
    ctx: SkillContext | None = None,
    guard_source: str | None = None,
    context_pack: str | None = None,
) -> PlanExecuteOutcome:
    ctx = ctx or SkillContext(user_input=user_text)
    ctx.user_input = user_text
    if context_pack:
        ctx.policy_state["context_pack"] = (context_pack or "").strip()
    origin = guard_source or "chat_box"
    ingress = _build_ingress_for_turn(
        user_text=user_text,
        artifact=artifact,
        guard_source=origin,
    )
    had_pending_review = bool(ctx.policy_state.get("pending_review"))
    if had_pending_review and not ingress.artifact_text and _pending_review_should_promote_raw_input(ingress):
        ingress = _coerce_pending_review_artifact(ingress)
    ctx.policy_state["ingress_payload"] = ingress_payload_to_dict(ingress)

    snap = _task_snapshot_from_ctx(ctx) or {}
    payload = _planner_payload(user_text, ctx)
    normalized_turn = _planner_source_turn_text(user_text, ingress)

    ingress_requires_dai = bool(ingress.requires_dai)
    review_pending_candidate = bool((ingress.metadata or {}).get("review_pending_candidate"))

    po = invoke_planner(
        user_text=payload,
        source_turn_text=normalized_turn,
        tool_catalog=get_tool_catalog(),
        model=model,
        base_url=base_url,
        temperature=temperature,
        context_pack=context_pack,
        ingress_summary=format_ingress_for_prompt(ingress),
        ingress_detected_task_type=str(ingress.detected_task_type),
        ingress_artifact_text=ingress.artifact_text,
        pending_review=had_pending_review,
        task_snapshot=snap,
        ingress_requires_dai=ingress_requires_dai,
        review_pending_candidate=review_pending_candidate,
    )
    v_todos, task_type_v, task_state_v, msg_v = validate_planner_output(
        user_text=normalized_turn,
        task_type=po.task_type,
        task_state=po.task_state,
        todos=list(po.todos),
        message=po.message,
        ingress_detected_task_type=str(ingress.detected_task_type),
        ingress_artifact_text=(ingress.artifact_text or "").strip(),
        pending_review=had_pending_review,
        task_snapshot=snap,
        context_pack=context_pack or "",
        ingress_requires_dai=ingress_requires_dai,
        review_pending_candidate=review_pending_candidate,
    )

    initial_plan = list(v_todos)
    todos: list[PlanStep] = list(v_todos)
    task_type = task_type_v
    task_state = task_state_v
    po_message = msg_v

    active_pending_review = bool(ctx.policy_state.get("pending_review"))
    results: list[SkillResult] = []
    executed_trace: list[PlanStep] = []

    return _run_replan_loop(
        normalized_turn=normalized_turn,
        task_type=task_type,
        task_state=task_state,
        initial_plan=initial_plan,
        todos=todos,
        po_message=po_message,
        ctx=ctx,
        results=results,
        executed_trace=executed_trace,
        model=model,
        base_url=base_url,
        temperature=temperature,
        context_pack=context_pack,
        active_pending_review=active_pending_review,
    )
