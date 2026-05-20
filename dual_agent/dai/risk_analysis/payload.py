"""組裝 Track A / 語意 LLM 用的結構化輸入。"""

from __future__ import annotations

from typing import Any

from dual_agent.dai.schemas import DAIRequest
from dual_agent.dai.user_db import extract_urls
from dual_agent.ingress import extract_entities


def text_for_analysis(req: DAIRequest) -> str:
    art = (req.artifact or "").strip()
    if art:
        return art
    return (req.user_text or "").strip()


def build_analysis_payload(
    req: DAIRequest,
    *,
    url_threat_hits: list[dict[str, Any]] | None = None,
    tls_findings: list[dict[str, Any]] | None = None,
    sender_tech_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = text_for_analysis(req)
    entities = extract_entities(text)
    urls = list(entities.urls) if entities.urls else extract_urls(text)
    expanded = list(urls)

    stc = dict(sender_tech_context or {})
    if getattr(req, "sender_display", None):
        stc.setdefault("sender_display", str(req.sender_display or "").strip())
    if getattr(req, "sender_number", None):
        stc.setdefault("sender_number", str(req.sender_number or "").strip())

    return {
        "text": text,
        "sender_display": stc.get("sender_display", ""),
        "sender_number": stc.get("sender_number", ""),
        "urls": urls,
        "expanded_urls": expanded,
        "url_threat_hits": list(url_threat_hits or []),
        "tls_findings": list(tls_findings or []),
        "sender_tech_context": stc,
        "entities": {
            "urls": list(entities.urls),
            "phones": list(entities.phones),
            "amounts": list(entities.amounts),
            "orgs": list(entities.orgs),
            "financial_terms": list(entities.financial_terms),
            "sensitive_terms": list(entities.sensitive_terms),
        },
    }
