"""
送審完成後常見追問的確定性回答（避免 LLM 把使用者自稱的名字當成助理名字）。
"""

from __future__ import annotations

import re
from typing import Any

from dual_agent.cai.context_layer import display_name_from_profile, extract_user_display_name_from_pack

_ASSISTANT_LABEL = "CAI 行動安全助理"


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def classify_follow_up_question(user_text: str) -> str | None:
    t = (user_text or "").strip()
    if not t:
        return None
    c = _compact(t)
    if re.search(r"^(有|會).{0,6}風險|有風險嗎|有沒有風險|危險嗎|安全嗎", c):
        return "risk_yn"
    if re.search(r"^我是誰|我是誰[?？]?$|你知道我是誰", c):
        return "user_identity"
    if re.search(r"^你是誰|你又是誰|你叫什麼|你是\s*alex|你是alex", t, re.IGNORECASE):
        return "assistant_identity"
    if re.search(r"誰發|誰傳|誰寄|來源是", c):
        return "message_source"
    return None


def _format_risk_answer_from_snapshot(snap: dict[str, Any]) -> str | None:
    score = snap.get("last_risk_score")
    if not isinstance(score, (int, float)):
        return None
    s = int(score)
    if s >= 70:
        level = "風險偏高，建議提高警覺"
    elif s >= 40:
        level = "中等風險，建議謹慎處理"
    else:
        level = "風險偏低"
    parts = [f"依先前送審結果，這則訊息風險分數為 {s}/100（{level}）。"]
    summ = str(snap.get("last_safety_summary") or "").strip()
    if summ:
        parts.append(summ[:200])
    action = str(snap.get("last_recommended_action") or "").strip()
    if action and action not in summ:
        parts.append(f"建議：{action}。")
    return "".join(parts)


def try_follow_up_direct_answer(
    user_text: str,
    *,
    context_pack: str | None,
    user_profile: dict[str, Any] | None = None,
    task_snapshot: dict[str, Any] | None = None,
    review_work_state: dict[str, Any] | None = None,
) -> str | None:
    """
    送審完成後的追問：能確定回答則回傳繁中文字，否則 None（交給 Replan LLM）。
    """
    snap = dict(task_snapshot or {})
    if str(snap.get("review_phase") or "").strip() != "review_completed":
        rws = review_work_state or {}
        if str(rws.get("phase") or "").strip() == "review_completed":
            snap = {
                "review_phase": "review_completed",
                "message_source": rws.get("message_source"),
                "artifact_excerpt": rws.get("artifact_excerpt"),
                "last_risk_score": (rws.get("dai") or {}).get("risk_score"),
                "last_safety_summary": (rws.get("dai") or {}).get("safety_summary"),
            }

    kind = classify_follow_up_question(user_text)
    if not kind:
        return None

    name = display_name_from_profile(user_profile) or extract_user_display_name_from_pack(context_pack)

    # 身份類追問：有 profile／Context 即可答，不必等送審完成
    if kind == "user_identity":
        if name:
            return f"您是 {name}。"
        return "我這邊還沒有您的稱呼；可在 App「編輯資料」設定，或直接告訴我您希望怎麼稱呼您。"

    if kind == "assistant_identity":
        if name and re.search(rf"你是\s*{re.escape(name)}", user_text, re.IGNORECASE):
            return (
                f"您叫 {name}。我是{_ASSISTANT_LABEL}，"
                f"和您的名字是不同的人。"
            )
        return (
            f"我是{_ASSISTANT_LABEL}，可協助您審查簡訊／通知風險，"
            f"並回答與已送審內容有關的追問。"
        )

    if str(snap.get("review_phase") or "").strip() != "review_completed":
        rws = review_work_state or {}
        if str(rws.get("phase") or "").strip() != "review_completed":
            return None

    if kind == "risk_yn":
        return _format_risk_answer_from_snapshot(snap)

    if kind == "message_source":
        src = str(snap.get("message_source") or "").strip()
        if src and src.lower() not in ("unknown", "（無）"):
            return f"依送審紀錄，這則內容的來源標記為：{src}。"
        excerpt = str(snap.get("artifact_excerpt") or "").strip()
        if excerpt:
            return f"系統未記下明確發送者編號；已送審內文摘要開頭為：{excerpt[:80]}…"
        return "目前沒有記錄到明確的發送者資訊，請查看簡訊或通知上的號碼／App 名稱。"

    return None
