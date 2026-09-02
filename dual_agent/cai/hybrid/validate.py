"""Hybrid：依 MessageFeatures 校正 Planner 輸出（取代 regex 護欄）。"""

from __future__ import annotations

from dual_agent.cai.hybrid.gates import allowed_skills_for
from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.cai.schemas import PlanStep

_REVIEW_ASK = "請貼上完整簡訊或訊息內容，我才能幫您審查風險。"
_OUT_SCOPE_MSG = "我主要協助檢視可疑訊息與詐騙風險，請貼上完整內容。"


def validate_planner_from_features(
    features: MessageFeatures,
    *,
    task_type: str,
    task_state: str,
    todos: list[PlanStep],
    message: str,
) -> tuple[list[PlanStep], str, str, str]:
    goal = features.primary_goal
    allowed = set(allowed_skills_for(features))
    filtered = [s for s in todos if (s.skill or "").strip().lower() in allowed]

    if goal == "out_of_scope":
        return [], "direct_response", "completed", message or _OUT_SCOPE_MSG

    if goal == "ask_missing_body" or features.gaps.missing_body_for_review:
        if not filtered:
            filtered = [
                PlanStep(
                    skill="ask_user",
                    args={"question": _REVIEW_ASK, "expected_task": "check"},
                )
            ]
        return filtered, "check", "waiting_input", message

    if goal == "review_sms":
        art = (features.content.artifact_text or "").strip()
        if art and not any(s.skill == "call_dai" for s in filtered):
            filtered = [PlanStep(skill="call_dai", args={"artifact": art, "sms_review": True})]
        elif not art:
            filtered = [
                PlanStep(
                    skill="ask_user",
                    args={"question": _REVIEW_ASK, "expected_task": "check"},
                )
            ]
            task_state = "waiting_input"
        task_type = task_type or "check"
        return filtered, task_type, task_state, message

    if goal == "remember_relation":
        label = (features.social.relation_label or "").strip()
        name = (features.social.relation_name or "").strip()
        if name and label and not filtered:
            filtered = [
                PlanStep(
                    skill="profile_remember_relation",
                    args={
                        "relation_label": label,
                        "relation_name": name,
                        "relation_category": features.social.relation_category,
                        "mode": "set",
                    },
                )
            ]
        elif not filtered:
            filtered = [
                PlanStep(
                    skill="ask_user",
                    args={"question": f"請告訴我{label or '這位親友'}的姓名。"},
                )
            ]
        return filtered, task_type or "direct_response", task_state, message

    if goal == "follow_up_review":
        return [], task_type or "check", task_state, message

    if goal == "recall_relation":
        return [], "direct_response", "completed", message

    # 過濾不在白名單的 skill
    return filtered, task_type, task_state, message
