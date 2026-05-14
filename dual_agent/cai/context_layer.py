"""
Memory / Context Layer（對齊設計圖）：

- Recent Context Buffer：最近 N 輪（預設 10）使用者／助理對話
- Rolling Summary：緩衝溢出時，將最舊一輪併入摘要（LLM，失敗則字串後援）
- Task Snapshot：上一輪結束時的 task_type / task_state

Context Packer：pack_context() → 供 Planner / Replan 前置的脈絡字串。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.config import context_buffer_max_rounds


@dataclass
class ConversationTurn:
    """單輪寫入緩衝：對話 + 任務／計畫／執行摘要（供日後 Replan 回答「剛做了什麼」等）。"""

    user: str
    assistant: str
    task_type: str = ""
    task_state: str = ""
    plan_summary: str = ""
    result_summary: str = ""


@dataclass
class SessionMemory:
    """單一工作階段記憶（程式內；未接 RAG / DB）。"""

    rolling_summary: str = ""
    recent_buffer: list[ConversationTurn] = field(default_factory=list)
    task_snapshot: dict[str, Any] = field(default_factory=dict)


def _compact_summary_value(value: Any, *, max_chars: int = 120) -> Any:
    if isinstance(value, str):
        s = " ".join(value.strip().split())
        if len(s) <= max_chars:
            return s
        return s[: max_chars - 1] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    try:
        s = json.dumps(value, ensure_ascii=False)
    except TypeError:
        s = str(value)
    s = " ".join(s.strip().split())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _summary_args_for_plan_step(skill: str, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    summarized: dict[str, Any] = {}
    for key, value in args.items():
        if key == "context_pack":
            summarized[key] = "（已省略）"
            continue
        if skill == "call_dai" and key == "artifact":
            summarized[key] = _compact_summary_value(value, max_chars=160)
            continue
        summarized[key] = _compact_summary_value(value)
    return summarized


def build_plan_summary(plan: list[Any] | None, *, max_steps: int = 12, max_json_chars: int = 320) -> str:
    """將本輪 plan（PlanStep 列表）壓成可進 Context 的一小段文字。"""
    if not plan:
        return "（本輪顯示之計畫步驟為空）"
    lines: list[str] = []
    for i, st in enumerate(plan[:max_steps], 1):
        sk = getattr(st, "skill", "?")
        args = _summary_args_for_plan_step(sk, getattr(st, "args", None) or {})
        try:
            aj = json.dumps(args, ensure_ascii=False)
        except TypeError:
            aj = str(args)
        if len(aj) > max_json_chars:
            aj = aj[: max_json_chars - 3] + "..."
        lines.append(f"{i}. {sk} {aj}")
    if len(plan) > max_steps:
        lines.append(f"…（另有 {len(plan) - max_steps} 步省略）")
    return "\n".join(lines)


def _truncate(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n…（已截斷）"


def pack_context(session: SessionMemory, *, max_chars_per_turn: int = 6000) -> str:
    """組成 Context Pack（繁體中文區塊標題，供 LLM 閱讀）。"""
    parts: list[str] = []
    rs = (session.rolling_summary or "").strip()
    if rs:
        parts.append(f"【長期摘要】\n{_truncate(rs, max_chars_per_turn * 2)}")
    if session.recent_buffer:
        chunks: list[str] = []
        for i, t in enumerate(session.recent_buffer, 1):
            u = _truncate(t.user, max_chars_per_turn)
            a = _truncate(t.assistant, max_chars_per_turn)
            meta_lines: list[str] = [
                f"task_type={_truncate((t.task_type or '（無）'), 80)}",
                f"task_state={_truncate((t.task_state or '（無）'), 80)}",
            ]
            if (t.plan_summary or "").strip():
                meta_lines.append(f"計畫摘要：\n{_truncate(t.plan_summary, max_chars_per_turn)}")
            if (t.result_summary or "").strip():
                meta_lines.append(f"執行結果摘要：\n{_truncate(t.result_summary, max_chars_per_turn)}")
            meta = "\n".join(meta_lines)
            chunks.append(
                f"（緩衝第 {i} 輪）\n{meta}\n使用者：{u}\n助理：{a}"
            )
        parts.append("【最近對話緩衝】\n" + "\n\n".join(chunks))
    ts = session.task_snapshot or {}
    if ts:
        parts.append("【上一輪任務狀態】\n" + json.dumps(ts, ensure_ascii=False))
    if not parts:
        return "（尚無累積脈絡：可視為對話開頭或尚未寫回記憶。）"
    return "\n\n".join(parts)


def merge_into_rolling_summary(
    existing_summary: str,
    turn: ConversationTurn,
    *,
    model: str,
    base_url: str,
    temperature: float = 0.2,
) -> str:
    """將移出緩衝的一輪對話併入長期摘要（單次 LLM 呼叫）。"""
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """你是對話記憶壓縮助手。請把「既有長期摘要」與「即將移出緩衝的一輪對話」合併成一段新的長期摘要（繁體中文）。
保留：使用者目標、約定、偏好、未完成事項、重要名詞與結論；若有「計畫摘要／執行結果摘要」，請保留其中與事實、工具行為相關的要點（例如曾搜尋什麼、成功與否）。
省略：寒暄、重複語句、與後續對話無關的細節。
只輸出摘要本文，不要標題、markdown、JSON。""",
            ),
            (
                "human",
                """【既有長期摘要】
{existing}

【本輪摘要（移出緩衝）】
task_type={task_type}
task_state={task_state}
計畫摘要：
{plan_summary}
執行結果摘要：
{result_summary}

使用者：{user}
助理：{assistant}""",
            ),
        ]
    )
    raw = (prompt | llm | StrOutputParser()).invoke(
        {
            "existing": (existing_summary or "").strip() or "（尚無）",
            "task_type": (turn.task_type or "").strip() or "（無）",
            "task_state": (turn.task_state or "").strip() or "（無）",
            "plan_summary": (turn.plan_summary or "").strip() or "（無）",
            "result_summary": (turn.result_summary or "").strip() or "（無）",
            "user": turn.user.strip(),
            "assistant": turn.assistant.strip(),
        }
    )
    return (raw or "").strip()


def _fallback_merge(existing_summary: str, turn: ConversationTurn) -> str:
    meta = "\n".join(
        [
            f"task_type={turn.task_type or '（無）'}",
            f"task_state={turn.task_state or '（無）'}",
            f"計畫：{(turn.plan_summary or '').strip() or '（無）'}",
            f"執行：{(turn.result_summary or '').strip() or '（無）'}",
        ]
    )
    block = f"{meta}\n使用者：{turn.user.strip()}\n助理：{turn.assistant.strip()}"
    if not (existing_summary or "").strip():
        return block
    return f"{existing_summary.strip()}\n\n---\n{block}"


def record_turn(
    session: SessionMemory,
    *,
    user: str,
    assistant: str,
    task_type: str,
    task_state: str,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    plan_summary: str = "",
    result_summary: str = "",
) -> None:
    """
    本輪結束後寫回：append 緩衝、更新 task_snapshot；若超過 CONTEXT_BUFFER_MAX_ROUNDS
    則反覆將最舊一輪壓入 rolling_summary。
    """
    cap = context_buffer_max_rounds()
    session.recent_buffer.append(
        ConversationTurn(
            user=user.strip(),
            assistant=(assistant or "").strip(),
            task_type=(task_type or "").strip(),
            task_state=(task_state or "").strip(),
            plan_summary=(plan_summary or "").strip(),
            result_summary=(result_summary or "").strip(),
        )
    )
    session.task_snapshot = {
        "task_type": (task_type or "").strip(),
        "task_state": (task_state or "").strip(),
    }
    while len(session.recent_buffer) > cap:
        oldest = session.recent_buffer.pop(0)
        try:
            session.rolling_summary = merge_into_rolling_summary(
                session.rolling_summary,
                oldest,
                model=model,
                base_url=base_url,
                temperature=temperature,
            )
        except Exception:
            session.rolling_summary = _fallback_merge(session.rolling_summary, oldest)
