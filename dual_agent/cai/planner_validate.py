"""
Planner 輸出一致性：結構矛盾與「問助理範圍」誤排 search_web 的校正。

執行順序（invoke_planner 內）：LLM 解析 → validate → apply_explicit_search_guard
→ 故「明文網搜」仍可由 guard 在 validate 之後補上。
"""

from __future__ import annotations

import re
from typing import Any, Final

from dual_agent.cai.context_layer import should_block_repeat_call_dai
from dual_agent.cai.planner_context import explicit_web_search_requested
from dual_agent.cai.schemas import PlanStep
from dual_agent.cai.skills.call_dai.handler import artifact_is_meta_only_intent

_REVIEW_ASK_USER_QUESTION = "請貼上完整簡訊或訊息內容，我才能幫您審查風險。"


def _todos_have_web_search(todos: list[PlanStep]) -> bool:
    return any(s.skill == "search_web" for s in todos)


def _todos_have_call_dai(todos: list[PlanStep]) -> bool:
    return any(s.skill == "call_dai" for s in todos)


def _pending_review_followup_should_drop_dai(user_text: str) -> bool:
    """
    待審補貨流程中，若本輪明顯是閒聊／天氣等新話題，勿硬留 call_dai。
    （仍依賴 Planner 排除誤排；此處為底線。）
    """
    t = (user_text or "").strip()
    if not t:
        return False
    if meta_assistant_or_chat_scope(t):
        return True
    if len(t) <= 40 and re.search(r"天氣|氣溫|下雨|降雨|颱風|風力", t):
        return True
    if re.match(r"^(嗨|嗨嗨|哈囉|你好|您好|謝謝|谢谢|OK|Ok|好的|不用了|沒事|没事)[!！。…\s]*$", t, re.I):
        return True
    return False


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


def _first_call_dai_step(todos: list[PlanStep]) -> PlanStep | None:
    for s in todos:
        if s.skill == "call_dai":
            return s
    return None


def _normalize_pending_call_dai_artifacts(todos: list[PlanStep], user_text: str) -> list[PlanStep]:
    """待審補貨：若 call_dai 未填 artifact，以本輪使用者原句補上。"""
    ut = (user_text or "").strip()
    if not ut:
        return todos
    out: list[PlanStep] = []
    for s in todos:
        if s.skill != "call_dai":
            out.append(s)
            continue
        args = dict(s.args or {})
        if not str(args.get("artifact") or "").strip():
            args["artifact"] = ut
            if not str(args.get("user_text") or "").strip():
                args["user_text"] = ut[:500]
        args.setdefault("sms_review", True)
        out.append(PlanStep(skill="call_dai", args=args))
    return out


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
    follow_up_on_review: bool = False,
    context_pack: str = "",
    task_snapshot: dict[str, Any] | None = None,
    ingress_requires_dai: bool = False,
    review_pending_candidate: bool = False,
) -> tuple[list[PlanStep], str, str, str]:
    """
    若 task_type／message 與「含 search_web 的 todos」矛盾，或屬助理範圍閒聊卻排了搜尋：
    清空 todos，改為 direct_response + answering，並在 message 前加上簡短校正說明（保留原 message）。
    """
    itt = (ingress_detected_task_type or "").strip().lower()
    art_stripped = (ingress_artifact_text or "").strip()

    if should_block_repeat_call_dai(
        task_snapshot,
        artifact_text=art_stripped,
        user_text=user_text,
    ) and _todos_have_call_dai(todos):
        prefix = "（規劃已校正：該則正文已審過，本輪改為 direct_response，不重複 call_dai。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [], "direct_response", "answering", new_msg

    if itt == "direct_response" and todos:
        prefix = "（規劃已校正：Ingress 為 direct_response，不應執行工具，已清空待辦。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [], "direct_response", "answering", new_msg

    gate_empty_artifact = (itt == "check" or (pending_review and itt == "unknown")) and (not art_stripped)
    if gate_empty_artifact:
        todos = _normalize_pending_call_dai_artifacts(todos, user_text)
        if pending_review and _pending_review_followup_should_drop_dai(user_text):
            todos = [s for s in todos if s.skill != "call_dai"]
        dai_st = _first_call_dai_step(todos)
        if dai_st is None:
            if todos:
                if pending_review and _todos_have_web_search(todos):
                    prefix = "（規劃已校正：目前仍在等待待審內容，已移除 search_web，改為 ask_user。）"
                    new_msg = f"{prefix}{message}".strip() if message else prefix
                    return [_review_ask_user_step()], "check", "waiting_input", new_msg
                return todos, task_type, task_state, message
            if pending_review and _pending_review_followup_should_drop_dai(user_text):
                prefix = (
                    "（規劃已校正：先前在等簡訊正文，本輪似新話題／閒聊，"
                    "已不強制追問待審內容；請依本輪主鍵回答。）"
                )
                new_msg = f"{prefix}{message}".strip() if message else prefix
                return [], "direct_response", "answering", new_msg
        if pending_review and dai_st is not None:
            d_art = str((dai_st.args or {}).get("artifact") or "").strip()
            if d_art and (not artifact_is_meta_only_intent(d_art)) and (
                not should_block_repeat_call_dai(
                    task_snapshot,
                    artifact_text=d_art,
                    user_text=user_text,
                )
            ):
                prefix_ok = "（規劃已確認：待審補貨，call_dai 之 artifact 取自本輪原句。）"
                new_msg = f"{prefix_ok}{message}".strip() if message else prefix_ok.strip()
                tt_fix = (task_type or "").strip().lower()
                if tt_fix not in ("check", "action", "unknown"):
                    tt_fix = "check"
                ts_fix = (task_state or "").strip().lower() or "running"
                if ts_fix not in ("new", "running", "waiting_input", "completed", "blocked", "answering"):
                    ts_fix = "running"
                if tt_fix == "unknown":
                    tt_fix = "check"
                return todos, tt_fix, ts_fix if ts_fix != "waiting_input" else "running", new_msg
        prefix = "（規劃已校正：審查任務尚未取得待審內容，已改為 ask_user，不可 call_dai／search_web。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [_review_ask_user_step()], "check", "waiting_input", new_msg

    if review_pending_candidate and _todos_have_web_search(todos):
        prefix = "（規劃已校正：尚缺待審正文（review_pending_candidate），不可用 search_web 代替，改為 ask_user。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [_review_ask_user_step()], "check", "waiting_input", new_msg

    if pending_review and _todos_have_web_search(todos):
        prefix = "（規劃已校正：目前仍在等待待審內容，已移除 search_web，改為 ask_user。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        return [_review_ask_user_step()], "check", "waiting_input", new_msg

    if (
        itt == "check"
        and ingress_requires_dai
        and art_stripped
        and not should_block_repeat_call_dai(
            task_snapshot,
            artifact_text=art_stripped,
            user_text=user_text,
        )
        and not _todos_have_call_dai(todos)
    ):
        prefix = "（規劃已校正：有待審正文且 requires_dai，已插入 call_dai。）"
        new_msg = f"{prefix}{message}".strip() if message else prefix
        dai_step = PlanStep(
            skill="call_dai",
            args={
                "artifact": art_stripped,
                "user_text": (user_text or "").strip()[:500] or "請審查這則訊息",
                "context_pack": "",
                "sms_review": True,
            },
        )
        return [dai_step], "check", "running", new_msg

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
