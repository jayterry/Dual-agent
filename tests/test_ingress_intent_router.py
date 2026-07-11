"""L1 Ingress Intent Router 單元測試（mock LLM，不依 Ollama）。"""

from __future__ import annotations

from dual_agent.cai.ingress_router import (
    build_payload_from_route_decision,
    guard_route_decision,
)
from dual_agent.cai.ingress_router.schemas import IngressRouteDecision
from dual_agent.ingress import (
    DetectedTaskType,
    InputOrigin,
    MessageSource,
    extract_entities,
    normalize_ingress,
)


def _mock_action_decision(_text: str, **_: object) -> IngressRouteDecision:
    return IngressRouteDecision(
        task_type="action",
        requires_dai=False,
        artifact_role="none",
        confidence=0.9,
        reason="mock_action",
    )


def _mock_check_link_decision(_text: str, **_: object) -> IngressRouteDecision:
    return IngressRouteDecision(
        task_type="check",
        requires_dai=True,
        artifact_role="artifact",
        confidence=0.9,
        reason="mock_check_link",
    )


def test_pure_url_uses_router_action() -> None:
    raw = "https://github.com"
    out = normalize_ingress(
        raw_input_text=raw,
        input_origin="chat_box",
        ingress_router_fn=_mock_action_decision,
    )
    assert str(out.detected_task_type) == "action"
    assert out.requires_dai is False
    assert (out.artifact_text or "").strip() == ""
    assert out.metadata.get("ingress_router") is True


def test_pure_url_fallback_without_router_mock() -> None:
    raw = "https://github.com"
    out = normalize_ingress(raw_input_text=raw, input_origin="chat_box", ingress_router_fn=lambda *_a, **_k: None)
    assert str(out.detected_task_type) == "action"
    assert out.requires_dai is False
    assert out.metadata.get("url_action_fallback") is True


def test_link_safety_review_via_router() -> None:
    raw = "幫我確認這個連結安不安全：https://bit.ly/abc"
    out = normalize_ingress(
        raw_input_text=raw,
        input_origin="chat_box",
        ingress_router_fn=_mock_check_link_decision,
    )
    assert str(out.detected_task_type) == "check"
    assert out.requires_dai is True
    assert "bit.ly" in (out.artifact_text or "")


def test_l0_overrides_llm_action_on_phishing() -> None:
    raw = "【XX銀行】您的帳戶異常，請點擊 https://fake.com 完成驗證"
    ents = extract_entities(raw)
    decision = IngressRouteDecision(
        task_type="action",
        requires_dai=False,
        artifact_role="none",
        confidence=0.9,
        reason="llm_wrong",
    )
    guarded = guard_route_decision(decision, raw, ents)
    assert guarded.task_type == "check"
    assert guarded.requires_dai is True
    assert guarded.artifact_role == "artifact"


def test_build_payload_pending_review() -> None:
    decision = IngressRouteDecision(
        task_type="check",
        requires_dai=False,
        artifact_role="pending_review",
        confidence=0.88,
        reason="mock",
    )
    out = build_payload_from_route_decision(
        raw="我收到一則簡訊",
        origin=InputOrigin.CHAT_BOX,
        entities=extract_entities("我收到一則簡訊"),
        safety_relevant=True,
        meta={},
        src=MessageSource(),
        optional_intent=None,
        decision=decision,
    )
    assert str(out.detected_task_type) == "check"
    assert out.requires_dai is False
    assert out.metadata.get("review_pending_candidate") is True


def test_router_low_confidence_falls_through_to_fallback() -> None:
    def _low(_t: str, **_: object) -> IngressRouteDecision:
        return IngressRouteDecision(
            task_type="action",
            requires_dai=False,
            artifact_role="none",
            confidence=0.1,
            reason="low",
        )

    raw = "https://example.com"
    out = normalize_ingress(raw_input_text=raw, input_origin="chat_box", ingress_router_fn=_low)
    assert str(out.detected_task_type) == "action"
    assert out.metadata.get("url_action_fallback") is True


def test_sms_share_skips_router() -> None:
    called = {"n": 0}

    def _spy(_t: str, **_: object) -> IngressRouteDecision:
        called["n"] += 1
        return _mock_action_decision(_t)

    raw = "【銀行】https://fake.com"
    out = normalize_ingress(
        raw_input_text=raw,
        input_origin="sms_share",
        ingress_router_fn=_spy,
    )
    assert called["n"] == 0
    assert out.requires_dai is True
    assert str(out.detected_task_type) == "check"
