"""何時觸發 L1 Ingress Intent Router。"""

from __future__ import annotations

from dual_agent.cai.review_entry_eligibility import looks_like_action_workflow
from dual_agent.ingress import IngressEntities, InputOrigin


def should_invoke_ingress_router(
    raw: str,
    entities: IngressEntities,
    *,
    origin: InputOrigin | str,
    safety_relevant: bool,
) -> bool:
    """CHAT_BOX、safety_relevant，且 action_workflow 未明確豁免時交由語意路由。"""
    origin_val = str(origin).strip().lower()
    if origin_val != InputOrigin.CHAT_BOX.value:
        return False
    text = (raw or "").strip()
    if not text or not safety_relevant:
        return False
    if looks_like_action_workflow(text, entities):
        return False
    return True
