"""IngressRouteDecision → IngressPayload，含 L0 安全覆寫。"""

from __future__ import annotations

import re
from typing import Any

from dual_agent.cai.ingress_router.schemas import IngressRouteDecision
from dual_agent.cai.review_entry_eligibility import _PHISHING_CTA_RE, _REVIEW_INTENT_ONLY_RE
from dual_agent.ingress import (
    DetectedTaskType,
    IngressEntities,
    IngressPayload,
    InputOrigin,
    InputRole,
    MessageSource,
    ReviewScope,
    _REVIEW_INTENT_RE,
    _split_chat_intent_and_artifact,
)

_LINK_SAFETY_REVIEW_RE = re.compile(
    r"(安不安全|有沒有風險|有風險嗎|危不危險|是不是詐騙|是否詐騙|可不可信|能不能點|要不要點)",
    re.IGNORECASE,
)


def _task_type_enum(value: str) -> DetectedTaskType:
    try:
        return DetectedTaskType(str(value).strip().lower())
    except ValueError:
        return DetectedTaskType.UNKNOWN


def guard_route_decision(
    decision: IngressRouteDecision,
    raw: str,
    entities: IngressEntities,
) -> IngressRouteDecision:
    """L0：絕對威脅／審查特徵覆寫 LLM 決策。"""
    text = (raw or "").strip()
    if not text:
        return decision

    split_intent, split_artifact, _ = _split_chat_intent_and_artifact(text)
    if split_artifact and _REVIEW_INTENT_RE.search(split_intent):
        return decision.model_copy(
            update={
                "task_type": "check",
                "requires_dai": True,
                "artifact_role": "artifact",
                "confidence": 1.0,
                "reason": "l0_colon_intent_artifact",
            }
        )

    if _REVIEW_INTENT_RE.search(text) or _REVIEW_INTENT_ONLY_RE.search(text):
        if _LINK_SAFETY_REVIEW_RE.search(text) or "詐騙" in text:
            has_body = bool(entities.urls) or bool(entities.financial_terms)
            return decision.model_copy(
                update={
                    "task_type": "check",
                    "requires_dai": has_body,
                    "artifact_role": "artifact" if has_body else "pending_review",
                    "confidence": 1.0,
                    "reason": "l0_review_intent",
                }
            )

    if entities.financial_terms or entities.sensitive_terms:
        if _PHISHING_CTA_RE.search(text) or (
            entities.financial_terms and entities.urls
        ):
            return decision.model_copy(
                update={
                    "task_type": "check",
                    "requires_dai": True,
                    "artifact_role": "artifact",
                    "confidence": 1.0,
                    "reason": "l0_phishing_or_financial",
                }
            )

    if re.search(r"[【\[][^】\]]{1,24}[】\]]", text) and entities.urls:
        return decision.model_copy(
            update={
                "task_type": "check",
                "requires_dai": True,
                "artifact_role": "artifact",
                "confidence": 1.0,
                "reason": "l0_org_bracket_url",
            }
        )

    return decision


def build_payload_from_route_decision(
    *,
    raw: str,
    origin: InputOrigin,
    entities: IngressEntities,
    safety_relevant: bool,
    meta: dict[str, Any],
    src: MessageSource,
    optional_intent: str | None,
    decision: IngressRouteDecision,
) -> IngressPayload:
    guarded = guard_route_decision(decision, raw, entities)
    out_meta = dict(meta)
    out_meta["ingress_router"] = True
    out_meta["ingress_route_reason"] = guarded.reason

    task = _task_type_enum(guarded.task_type)
    requires_dai = bool(guarded.requires_dai)
    role = guarded.artifact_role

    if role == "artifact" and requires_dai:
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.ARTIFACT,
            intent_text=(optional_intent or "").strip(),
            artifact_text=raw,
            review_scope=ReviewScope.RAW_INPUT,
            detected_task_type=DetectedTaskType.CHECK,
            requires_dai=True,
            safety_relevant=True,
            message_source=src,
            entities=entities,
            metadata=out_meta,
        )

    if role == "pending_review" or (
        task == DetectedTaskType.CHECK and not requires_dai
    ):
        out_meta["review_pending_candidate"] = True
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.INTENT,
            intent_text=raw,
            artifact_text="",
            review_scope=ReviewScope.NONE,
            detected_task_type=DetectedTaskType.CHECK,
            requires_dai=False,
            safety_relevant=safety_relevant,
            message_source=src,
            entities=entities,
            metadata=out_meta,
        )

    if task == DetectedTaskType.ACTION:
        out_meta["action_workflow"] = True
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.INTENT,
            intent_text=raw,
            artifact_text="",
            review_scope=ReviewScope.NONE,
            detected_task_type=DetectedTaskType.ACTION,
            requires_dai=False,
            safety_relevant=safety_relevant,
            message_source=src,
            entities=entities,
            metadata=out_meta,
        )

    if task == DetectedTaskType.DIRECT_RESPONSE:
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.INTENT,
            intent_text=raw,
            artifact_text="",
            review_scope=ReviewScope.NONE,
            detected_task_type=DetectedTaskType.DIRECT_RESPONSE,
            requires_dai=False,
            safety_relevant=False,
            message_source=src,
            entities=entities,
            metadata=out_meta,
        )

    if task == DetectedTaskType.CHECK and requires_dai:
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.ARTIFACT,
            intent_text=(optional_intent or "").strip(),
            artifact_text=raw,
            review_scope=ReviewScope.RAW_INPUT,
            detected_task_type=DetectedTaskType.CHECK,
            requires_dai=True,
            safety_relevant=True,
            message_source=src,
            entities=entities,
            metadata=out_meta,
        )

    return IngressPayload(
        raw_input_text=raw,
        input_origin=origin,
        input_role=InputRole.INTENT,
        intent_text=optional_intent or raw,
        artifact_text="",
        review_scope=ReviewScope.NONE,
        detected_task_type=task,
        requires_dai=requires_dai,
        safety_relevant=safety_relevant,
        message_source=src,
        entities=entities,
        metadata=out_meta,
    )
