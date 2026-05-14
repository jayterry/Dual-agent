"""
CAI 主迴路（嚴格依流程圖）：

User（+ 上下文占位）→ Planner LLM →
  - Todo 為空 → Replan LLM（不經 Executor）→ 最終回答／等待輸入
  - Todo 非空 → Executor 僅執行 Todo[0] → Replan LLM → …（直到完成或達上限）

不含：獨立意圖分類器、policy_gate、nl_router、chat_responder 平行路徑。
"""

from __future__ import annotations

import json

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL, max_executor_steps, max_replan_iterations
from dual_agent.cai.executor import execute_step, format_results_for_display
from dual_agent.cai.planner_llm import invoke_planner
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
    if bool((ingress.metadata or {}).get("threat_review_candidate")):
        return True
    return ingress.detected_task_type == DetectedTaskType.UNKNOWN and ingress.safety_relevant


def _coerce_pending_review_artifact(ingress: IngressPayload) -> IngressPayload:
    ingress.input_role = InputRole.ARTIFACT
    ingress.artifact_text = ingress.raw_input_text
    ingress.detected_task_type = DetectedTaskType.CHECK
    ingress.requires_dai = True
    ingress.safety_relevant = True
    ingress.review_scope = ReviewScope.RAW_INPUT
    ingress.metadata["pending_review_artifact"] = True
    return ingress


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


def run_plan_and_execute(
    *,
    user_text: str,
    model: str = OLLAMA_MODEL,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.2,
    ctx: SkillContext | None = None,
    guard_source: str | None = None,
    context_pack: str | None = None,
) -> PlanExecuteOutcome:
    ctx = ctx or SkillContext(user_input=user_text)
    ctx.user_input = user_text
    ingress = normalize_ingress(raw_input_text=user_text, input_origin=guard_source or "chat_box")
    had_pending_review = bool(ctx.policy_state.get("pending_review"))
    if had_pending_review and not ingress.artifact_text and _pending_review_should_promote_raw_input(ingress):
        ingress = _coerce_pending_review_artifact(ingress)
    ctx.policy_state["ingress_payload"] = ingress_payload_to_dict(ingress)

    if ingress.detected_task_type == DetectedTaskType.CHECK and not (ingress.artifact_text or "").strip():
        return _direct_review_ask_user(ctx, ingress)

    payload = _planner_payload(user_text, ctx)
    normalized_turn = _planner_source_turn_text(user_text, ingress)
    direct_call_dai = (
        ingress.detected_task_type == DetectedTaskType.CHECK
        and ingress.requires_dai
        and bool((ingress.artifact_text or "").strip())
        and (had_pending_review or bool((ingress.metadata or {}).get("threat_review_candidate")))
    )
    if direct_call_dai:
        _clear_pending_review(ctx)
        todos, task_type, task_state = _direct_review_call_dai_plan(ingress, context_pack)
        initial_plan = list(todos)
        po_message = "（已由前置審查入口規則直接轉入 call_dai）"
        todos_runtime: list[PlanStep] = list(todos)
        task_type_runtime = task_type
        task_state_runtime = task_state
    else:
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
        )
        initial_plan = list(po.todos)
        todos_runtime = list(po.todos)
        task_type_runtime = po.task_type
        task_state_runtime = po.task_state
        po_message = po.message

    todos: list[PlanStep] = list(todos_runtime)
    task_type = task_type_runtime
    task_state = task_state_runtime
    active_pending_review = bool(ctx.policy_state.get("pending_review"))
    results: list[SkillResult] = []
    observation_lines: list[str] = []
    observation_log: str | None = None
    # 僅記錄「實際跑過 Executor」的步驟（含 Replan 後插入的 search_web），供 UI 與 initial_plan 不一致時對齊
    executed_trace: list[PlanStep] = []

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
