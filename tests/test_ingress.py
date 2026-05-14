"""Ingress normalize：deterministic input structuring before Planner."""

from __future__ import annotations

from dual_agent.ingress import (
    DetectedTaskType,
    InputOrigin,
    InputRole,
    ReviewScope,
    normalize_ingress,
)


def test_sms_share_financial_sms_defaults_to_artifact_review() -> None:
    raw = "【XX銀行】您的帳戶異常，請立即點擊 https://fake.com 完成驗證"
    out = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.SMS_SHARE)
    assert out.input_role == InputRole.ARTIFACT
    assert out.artifact_text == raw
    assert out.review_scope == ReviewScope.ARTIFACT_ONLY
    assert out.detected_task_type == DetectedTaskType.CHECK
    assert out.requires_dai is True
    assert out.safety_relevant is True
    assert "https://fake.com" in out.entities.urls
    assert any(x in out.entities.financial_terms for x in ("銀行", "帳戶"))


def test_chat_box_review_intent_without_artifact() -> None:
    raw = "幫我看這是不是詐騙"
    out = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.CHAT_BOX)
    assert out.input_role == InputRole.INTENT
    assert out.intent_text == raw
    assert out.artifact_text == ""
    assert out.review_scope == ReviewScope.NONE
    assert out.detected_task_type == DetectedTaskType.CHECK
    assert out.requires_dai is False
    assert out.safety_relevant is True


def test_chat_box_mixed_intent_and_sms_body() -> None:
    raw = "幫我看這是不是詐騙：【XX銀行】您的帳戶異常，請點擊 https://fake.com"
    out = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.CHAT_BOX)
    assert out.input_role == InputRole.MIXED
    assert "幫我看這是不是詐騙" in out.intent_text
    assert "【XX銀行】" in out.artifact_text
    assert out.review_scope == ReviewScope.ARTIFACT_ONLY
    assert out.detected_task_type == DetectedTaskType.CHECK
    assert out.requires_dai is True


def test_unknown_origin_with_url_and_financial_terms_sends_review() -> None:
    raw = "帳戶異常，請前往 https://fake.com"
    out = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.UNKNOWN)
    assert out.safety_relevant is True
    assert out.requires_dai is True
    assert out.review_scope == ReviewScope.RAW_INPUT
    assert out.artifact_text == raw


def test_general_chat_is_direct_response() -> None:
    out = normalize_ingress(raw_input_text="你好", input_origin=InputOrigin.CHAT_BOX)
    assert out.detected_task_type == DetectedTaskType.DIRECT_RESPONSE
    assert out.requires_dai is False
    assert out.review_scope == ReviewScope.NONE
    assert out.artifact_text == ""


def test_background_info_is_not_auto_reviewed() -> None:
    out = normalize_ingress(raw_input_text="我現在在冰島", input_origin=InputOrigin.CHAT_BOX)
    assert out.detected_task_type == DetectedTaskType.DIRECT_RESPONSE
    assert out.requires_dai is False
    assert out.safety_relevant is False
    assert out.artifact_text == ""


def test_field_name_should_not_decide_review_path() -> None:
    raw = "幫我看這是不是詐騙"
    sms_like = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.SMS_SHARE)
    chat_like = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.CHAT_BOX)
    assert sms_like.input_role == InputRole.ARTIFACT
    assert sms_like.requires_dai is True
    assert sms_like.artifact_text == raw
    assert chat_like.input_role == InputRole.INTENT
    assert chat_like.requires_dai is False
    assert chat_like.artifact_text == ""


def test_review_help_request_becomes_pending_candidate() -> None:
    out = normalize_ingress(raw_input_text="有人發簡訊給她", input_origin=InputOrigin.CHAT_BOX)
    assert out.detected_task_type == DetectedTaskType.CHECK
    assert out.artifact_text == ""
    assert out.requires_dai is False
    assert out.safety_relevant is True
    assert out.review_scope == ReviewScope.NONE
    assert out.metadata.get("review_pending_candidate") is True


def test_threatening_sms_body_becomes_raw_input_review() -> None:
    raw = "簡訊說他的三個小孩被綁架了，要從最大的 alex 開始殺，除非給他 300 萬"
    out = normalize_ingress(raw_input_text=raw, input_origin=InputOrigin.CHAT_BOX)
    assert out.safety_relevant is True
    assert out.detected_task_type == DetectedTaskType.CHECK
    assert out.artifact_text == raw
    assert out.requires_dai is True
    assert out.review_scope == ReviewScope.RAW_INPUT
    assert out.metadata.get("threat_review_candidate") is True
