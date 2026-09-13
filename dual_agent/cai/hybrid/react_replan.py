"""Hybrid ReAct Replan：單步 thought + action，轉接既有 ReplanOutput 迴圈。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.cai.hybrid.gates import allowed_skills_for, skill_allowed
from dual_agent.cai.hybrid.prompts import load_prompt
from dual_agent.cai.hybrid.schemas import MessageFeatures, ReActAction, ReActOutput
from dual_agent.cai.skills.quick_reply.handler import KIND_OUT_OF_SCOPE, render_reply
from dual_agent.cai.pipeline_progress import advance_pipeline_node, append_thinking
from dual_agent.cai.schemas import PlanStep, ReplanOutput
from dual_agent.llm_json import coerce_llm_text, invoke_and_parse_json
from dual_agent.skill_types import SkillContext

_OUT_SCOPE_REPLY = render_reply(KIND_OUT_OF_SCOPE)


def _parse_react_action(raw: dict[str, Any]) -> ReActAction:
    act = raw.get("action")
    if not isinstance(act, dict):
        act = raw
    typ = coerce_llm_text(act.get("type")).lower() or "finish"
    if typ not in ("tool", "ask_user", "finish", "decline"):
        typ = "finish"
    skill = coerce_llm_text(act.get("skill")) or None
    args = act.get("args") if isinstance(act.get("args"), dict) else {}
    question = coerce_llm_text(act.get("question")) or None
    final_answer = coerce_llm_text(act.get("final_answer")) or None
    return ReActAction(
        type=typ,  # type: ignore[arg-type]
        skill=skill,
        args={str(k): v for k, v in (args or {}).items()},
        question=question,
        final_answer=final_answer,
    )


def react_to_replan_output(
    react: ReActOutput,
    *,
    features: MessageFeatures | None = None,
    fallback_task_state: str = "running",
) -> ReplanOutput:
    """ReAct 單步 action → 既有 ReplanOutput（供 _run_replan_loop 使用）。"""
    act = react.action
    if act.type in ("finish", "decline"):
        fa = (act.final_answer or "").strip()
        if act.type == "decline" and not fa:
            fa = _OUT_SCOPE_REPLY
        return ReplanOutput(
            complete=True,
            final_answer=fa,
            updated_todos=[],
            task_state="completed" if fallback_task_state != "waiting_input" else "answering",
            waiting_input=False,
            user_prompt="",
        )
    if act.type == "ask_user":
        q = (act.question or "請補充資訊。").strip()
        return ReplanOutput(
            complete=False,
            final_answer="",
            updated_todos=[],
            task_state="waiting_input",
            waiting_input=True,
            user_prompt=q,
        )
    skill = (act.skill or "").strip().lower()
    if features is not None and skill and not skill_allowed(features, skill):
        return ReplanOutput(
            complete=True,
            final_answer=_OUT_SCOPE_REPLY,
            updated_todos=[],
            task_state="completed",
            waiting_input=False,
            user_prompt="",
        )
    if not skill:
        return ReplanOutput(
            complete=True,
            final_answer=(act.final_answer or "（無有效工具步驟）").strip(),
            updated_todos=[],
            task_state="completed",
        )
    return ReplanOutput(
        complete=False,
        final_answer="",
        updated_todos=[PlanStep(skill=skill, args=dict(act.args or {}))],
        task_state="running",
        waiting_input=False,
        user_prompt="",
    )


def invoke_react_replan(
    *,
    user_text: str,
    task_type: str,
    task_state: str,
    remaining_todos: list[PlanStep],
    observation_log: str | None,
    planner_message: str,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    context_pack: str | None = None,
    message_features: MessageFeatures | None = None,
    allowed_skills: list[str] | None = None,
    pending_review: bool = False,
    pipeline_ctx: SkillContext | None = None,
) -> ReActOutput:
    if pipeline_ctx is not None:
        advance_pipeline_node(pipeline_ctx, "replan_llm", model=model)
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    system = load_prompt("react_replan_system")
    feats = message_features
    if allowed_skills is None and feats is not None:
        allowed_skills = allowed_skills_for(feats)
    allowed = allowed_skills or []
    todos_json = json.dumps(
        [{"skill": s.skill, "args": s.args} for s in remaining_todos],
        ensure_ascii=False,
    )
    obs = (observation_log or "").strip() or "（尚無執行結果）"
    mf_json = feats.model_dump_json_compact() if feats is not None else "（無）"

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system),
            (
                "human",
                """【Context Pack】
{context_pack}

【MessageFeatures】
{message_features_json}

【本輪允許 skills】
{allowed_skills}

使用者訊息：
{user_text}

task_type={task_type}
task_state={task_state}
pending_review={pending_review}

Planner 說明：
{planner_message}

Planner 初稿 remaining_todos：
{remaining_json}

observation_log：
{obs}
""".strip(),
            ),
        ]
    )
    chain = prompt | llm | StrOutputParser()
    inputs = {
        "context_pack": (context_pack or "").strip() or "（無）",
        "message_features_json": mf_json,
        "allowed_skills": ", ".join(allowed) if allowed else "（依 MessageFeatures）",
        "user_text": user_text.strip(),
        "task_type": task_type,
        "task_state": task_state,
        "pending_review": "true" if pending_review else "false",
        "planner_message": (planner_message or "").strip() or "（無）",
        "remaining_json": todos_json,
        "obs": obs,
    }

    def _invoke() -> str:
        return chain.invoke(inputs)

    def _retry_invoke() -> str:
        retry = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "只輸出 JSON：thought, action（含 type/skill/args/question/final_answer）。不要 markdown。",
                ),
                ("human", "使用者：{user_text}\nobservation：{obs}"),
            ]
        )
        return (retry | llm | StrOutputParser()).invoke(
            {"user_text": user_text.strip(), "obs": obs[:4000]}
        )

    obj = invoke_and_parse_json(_invoke, retry_invoke=_retry_invoke)
    thought = coerce_llm_text(obj.get("thought"))
    action = _parse_react_action(obj if isinstance(obj, dict) else {})
    out = ReActOutput(thought=thought, action=action)
    if pipeline_ctx is not None:
        trace = pipeline_ctx.policy_state.setdefault("react_trace", [])
        if isinstance(trace, list):
            trace.append({"thought": out.thought, "action": out.action.model_dump()})
        thought = (out.thought or "").strip()
        if thought:
            append_thinking(pipeline_ctx, "react", "為什麼這樣做", thought)
    return out
