"""
Planner 輸出一致性：結構矛盾與「問助理範圍」誤排 search_web 的校正。

執行順序（invoke_planner 內）：LLM 解析 → validate → apply_explicit_search_guard
→ 故「明文網搜」仍可由 guard 在 validate 之後補上。
"""

from __future__ import annotations

import re
from typing import Final

from dual_agent.cai.planner_context import explicit_web_search_requested
from dual_agent.cai.schemas import PlanStep

_REVIEW_ASK_USER_QUESTION = "請貼上完整簡訊或訊息內容，我才能幫您審查風險。"


def _todos_have_web_search(todos: list[PlanStep]) -> bool:
    return any(s.skill == "search_web" for s in todos)


def meta_assistant_or_chat_scope(user_text: str) -> bool:
    """
    高精度：使用者主要在問「助理自身／閒聊接續」，不應觸發網搜。
    刻意收斂 pattern 數量，避免大包關鍵字表。
    """
    t = (user_text or "").strip()
    if not t:
        return False
    patterns: Final[tuple[str, ...]] = (
        r"(想知道|想了解).{0,14}(你|您|助理).{0,10}(可以|能|會).{0,8}(做|幫).{0,6}(什麼|甚麼|哪些)",
        r"你(可以|能|會).{0,8}(做|幫).{0,10}(什麼|甚麼|哪些)",
        r"(像是|例如).{0,8}(執行|做).{0,10}(什麼|甚麼).{0,6}(任務|事情|事)",
        r"(什麼|哪些).{0,4}(任務|事)",
        r"^(真的嗎|真的假的|有嗎|有這種事嗎)[?？!！。…\s]*$",
        r"^我叫[\w\u4e00-\u9fff\u00b7]{1,24}$",
        r"(?i)(replan|replanner|這個助理|本助理|CAI|Planner).{0,12}(能|可以).{0,8}(做|幫).{0,8}(什麼|甚麼|哪些|任務)",
    )
    return any(re.search(p, t) for p in patterns)


def message_implies_no_tools(message: str) -> bool:
    m = (message or "").strip()
    if not m:
        return False
    needles: Final[tuple[str, ...]] = (
        "不需要工具",
        "不需工具",
        "不用工具",
        "一般問答",
        "無需工具",
        "不必使用工具",
        "不須工具",
        "屬於閒聊",
        "助理能力",
        "詢問助理",
    )
    return any(n in m for n in needles)


def _review_ask_user_step() -> PlanStep:
    return PlanStep(
        skill="ask_user",
        args={
            "question": _REVIEW_ASK_USER_QUESTION,
            "rationale": "需要待審內容才能進行威脅或詐騙風險審查",
            "expected_task": "check",
        },
    )


def validate_planner_output(
    *,
    user_text: str,
    task_type: str,
    task_state: str,
    todos: list[PlanStep],
    message: str,
    ingress_detected_task_type: str = "",
    ingress_artifact_text: str = "",
    pending_review: bool = False,
) -> tuple[list[PlanStep], str, str, str]:
    """
    若 task_type／message 與「含 search_web 的 todos」矛盾，或屬助理範圍閒聊卻排了搜尋：
    清空 todos，改為 direct_response + answering，並在 message 前加上簡短校正說明（保留原 message）。
    """
    if (ingress_detected_task_type or "").strip().lower() == "check" and not (ingress_artifact_text or "").strip():
        prefix = "（規劃已校正：審查任務尚未取得待審內容，已改為 ask_user，不可 search_web。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [_review_ask_user_step()], "check", "waiting_input", new_msg

    if pending_review and _todos_have_web_search(todos):
        prefix = "（規劃已校正：目前仍在等待待審內容，已移除 search_web，改為 ask_user。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [_review_ask_user_step()], "check", "waiting_input", new_msg

    if explicit_web_search_requested(user_text):
        return todos, task_type, task_state, message

    if not _todos_have_web_search(todos):
        return todos, task_type, task_state, message

    tt = (task_type or "").strip().lower()
    msg = (message or "").strip()

    conflict_direct = tt in ("direct_response", "general_qa")
    conflict_message = message_implies_no_tools(msg)
    meta = meta_assistant_or_chat_scope(user_text)

    if conflict_direct or conflict_message or meta:
        prefix = "（規劃已校正：此輪為助理範圍或不需工具之任務對答，已移除不應觸發的 search_web。）"
        new_msg = f"{prefix}{msg}".strip() if msg else prefix.strip()
        return [], "direct_response", "answering", new_msg

    return todos, task_type, task_state, message
