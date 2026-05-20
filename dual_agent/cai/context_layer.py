"""
Memory / Context Layer（對齊設計圖）：

- 長期記憶：user_profile（App 註冊基本資料）+ rolling_summary（對話壓縮摘要）
- Recent Context Buffer：最近 N 輪使用者／助理對話
- Task Snapshot：上一輪 task_type / task_state（送審後含 review_phase、last_risk_score 等）

Context Packer：pack_context() → 供 Planner / Replan / DAI 共用的脈絡字串。
"""

from __future__ import annotations

import json
import re
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
    user_profile: dict[str, Any] = field(default_factory=dict)


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


def _norm_artifact_key(text: str) -> str:
    return "".join(str(text or "").split()).strip().lower()


_ASSISTANT_NAME = "CAI"

_USER_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"我(?:是|叫)(?:你(?:的)?)?(?:主人|老闆|使用者)?\s*([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\u00b7.\-]{0,24})",
        re.IGNORECASE,
    ),
    re.compile(
        r"display_name=([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\u00b7.\-]{0,24})",
        re.IGNORECASE,
    ),
)


def extract_user_display_name_from_pack(context_pack: str | None) -> str | None:
    pack = (context_pack or "").strip()
    if not pack:
        return None
    skip = frozenset({"誰", "什麼", "你的", "助手", "助理", "主人"})
    found: list[tuple[int, str]] = []
    for pat in _USER_NAME_PATTERNS:
        for m in pat.finditer(pack):
            name = (m.group(1) or "").strip()
            if name and name not in skip:
                found.append((m.start(), name))
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    return found[-1][1]


extract_user_display_name = extract_user_display_name_from_pack


def merge_user_profile(session: SessionMemory, profile: dict[str, Any] | None) -> None:
    """合併 App 傳入的 user_profile（display_name、user_id）。"""
    if not profile or not isinstance(profile, dict):
        return
    merged = dict(session.user_profile or {})
    uid = str(profile.get("user_id") or profile.get("userId") or "").strip()
    name = str(profile.get("display_name") or profile.get("displayName") or "").strip()
    if uid:
        merged["user_id"] = uid
    if name:
        merged["display_name"] = name
    merged["assistant_name"] = _ASSISTANT_NAME
    session.user_profile = merged


def display_name_from_profile(user_profile: dict[str, Any] | None) -> str | None:
    if not user_profile:
        return None
    name = str(user_profile.get("display_name") or "").strip()
    return name or None


def format_long_term_memory_block(session: SessionMemory, *, max_summary_chars: int = 8000) -> str:
    """【長期記憶】= 使用者基本資料 + 對話長期摘要。"""
    lines: list[str] = ["【長期記憶】"]
    prof = session.user_profile or {}
    if prof:
        lines.append("── 使用者基本資料（App 註冊；「我是誰」答此稱呼，「你是誰」答 CAI 助理）")
        uid = str(prof.get("user_id") or "").strip()
        name = str(prof.get("display_name") or "").strip()
        if uid:
            lines.append(f"user_id={uid}")
        if name:
            lines.append(f"display_name={name}")
        lines.append(f"assistant_name={prof.get('assistant_name') or _ASSISTANT_NAME}")
    rs = (session.rolling_summary or "").strip()
    if rs:
        lines.append("── 對話長期摘要")
        lines.append(_truncate(rs, max_summary_chars))
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def is_same_artifact_as_snapshot(
    task_snapshot: dict[str, Any] | None,
    artifact_text: str,
) -> bool:
    """本輪附带的正文是否與 snapshot 中已審的 artifact_key 相同。"""
    snap = dict(task_snapshot or {})
    stored_key = str(snap.get("artifact_key") or "").strip()
    if not stored_key:
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return False
    new_key = _norm_artifact_key(new_art)
    if new_key == stored_key:
        return True
    if len(stored_key) >= 4 and (stored_key in new_key or new_key in stored_key):
        return True
    return False


def should_block_repeat_call_dai(
    task_snapshot: dict[str, Any] | None,
    *,
    artifact_text: str = "",
    user_text: str = "",
) -> bool:
    """
    是否應阻止本輪再排 call_dai（底線，非路由模式）：
    已完成審查且本輪無新正文，或正文與已審相同，且使用者未要求再審。
    """
    snap = dict(task_snapshot or {})
    if str(snap.get("review_phase") or "").strip() != "review_completed":
        return False
    if re.search(r"再審|重新審|重審|審查一次", (user_text or "").strip()):
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return True
    return is_same_artifact_as_snapshot(snap, new_art)


def is_follow_up_on_completed_review(
    user_text: str,
    *,
    task_snapshot: dict[str, Any] | None = None,
    review_work_state: dict[str, Any] | None = None,
    artifact_text: str = "",
) -> bool:
    """向後相容：已審完成且本輪未附新正文（或與已審相同）。"""
    del user_text
    snap = dict(task_snapshot or {})
    if not snap and review_work_state:
        snap = {
            "review_phase": review_work_state.get("phase"),
            "artifact_key": review_work_state.get("artifact_key"),
        }
    if str(snap.get("review_phase") or "").strip() != "review_completed":
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return True
    return is_same_artifact_as_snapshot(snap, new_art)


def format_work_state_summary(task_snapshot: dict[str, Any] | None) -> str:
    """將 task_snapshot 轉成 Planner 可讀的繁中摘要（JSON 仍保留於 pack_context）。"""
    snap = dict(task_snapshot or {})
    if not snap:
        return ""
    phase = str(snap.get("review_phase") or "").strip() or "（未送審）"
    lines = [f"階段：{phase}"]
    score = snap.get("last_risk_score")
    if isinstance(score, (int, float)):
        lines.append(f"上次風險分數：{int(score)}/100")
    summ = str(snap.get("last_safety_summary") or "").strip()
    if summ:
        lines.append(f"上次摘要：{summ[:200]}")
    ex = str(snap.get("artifact_excerpt") or "").strip()
    if ex:
        lines.append(f"已審正文摘要：{ex[:120]}…")
    src = str(snap.get("message_source") or "").strip()
    if src and src.lower() not in ("unknown", "（無）"):
        lines.append(f"來源：{src}")
    if phase == "review_completed":
        lines.append(
            "若本輪 user prompt 僅詢問分數／身份／來源，通常 todos=[]、勿 call_dai；"
            "若本輪附全新可疑正文或使用者要求再審，可 call_dai。"
        )
    return "\n".join(lines)


def pack_context(session: SessionMemory, *, max_chars_per_turn: int = 6000) -> str:
    """組成 Context Pack（繁體中文區塊標題，供 LLM 閱讀）。"""
    parts: list[str] = []
    lt = format_long_term_memory_block(session, max_summary_chars=max_chars_per_turn * 2)
    if lt:
        parts.append(lt)
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
        summary = format_work_state_summary(ts)
        block = "【上一輪任務狀態】\n"
        if summary:
            block += summary + "\n\n"
        block += json.dumps(ts, ensure_ascii=False)
        parts.append(block)
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


def record_turn_after_review(
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
    artifact: str = "",
    message_source: str = "",
    input_origin: str = "",
    dai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """送審結束：與一般聊天相同 record_turn，並擴充 task_snapshot 供追問。"""
    record_turn(
        session,
        user=user,
        assistant=assistant,
        task_type=task_type,
        task_state=task_state,
        model=model,
        base_url=base_url,
        temperature=temperature,
        plan_summary=plan_summary,
        result_summary=result_summary,
    )
    art = (artifact or "").strip()
    dai_payload = dict(dai or {})
    snap: dict[str, Any] = {
        "task_type": (task_type or "check").strip(),
        "task_state": (task_state or "completed").strip(),
        "review_phase": "review_completed",
        "has_dai_result": True,
        "message_source": (message_source or "").strip() or "unknown",
        "input_origin": (input_origin or "").strip() or "unknown",
        "artifact_key": _norm_artifact_key(art),
        "artifact_excerpt": _truncate(art, 400),
    }
    score = dai_payload.get("risk_score")
    if isinstance(score, (int, float)):
        snap["last_risk_score"] = int(score)
    summ = str(dai_payload.get("safety_summary") or "").strip()
    if summ:
        snap["last_safety_summary"] = _truncate(summ, 500)
    action = str(dai_payload.get("recommended_cai_action") or "").strip()
    if action:
        snap["last_recommended_action"] = action
    session.task_snapshot = snap
    return snap


# 向後相容別名
record_review_outcome = record_turn_after_review
