"""Payload 特徵（系統解析）。"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from dual_agent.dai.fraud_dual.shared.keywords import (
    APK_HINTS,
    HIGH_RISK_PERMISSIONS,
    OUTSIDE_STORE_HINTS,
    SHORTENERS,
    SUSPICIOUS_TLDS,
)
from dual_agent.dai.fraud_dual.shared.schemas import PayloadFeatures

_URL_RE = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"']+|(?:[a-z0-9-]+\.)+(?:com|tw|net|org|xyz|top|vip|click|icu|app)(?:/[^\s<>\"']*)?"
)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)|(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,4}(?!\d)"
)
_ACCOUNT_RE = re.compile(
    r"(?<!\d)\d{10,16}(?!\d)|0x[a-fA-F0-9]{40}\b|T[1-9A-HJ-NP-Za-km-z]{33}"
)


def _extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def _host_of(url: str) -> str:
    candidate = url if "://" in url else f"http://{url}"
    try:
        return (urlparse(candidate).hostname or "").lower()
    except Exception:
        return ""


def extract_payload_features(text: str) -> PayloadFeatures:
    urls = _extract_urls(text)
    contains_url = 1 if urls else 0

    url_is_shortener = 0
    suspicious_tld = 0
    for u in urls:
        host = _host_of(u)
        if any(s in host for s in SHORTENERS):
            url_is_shortener = 1
        if any(host.endswith(tld) for tld in SUSPICIOUS_TLDS):
            suspicious_tld = 1

    t_lower = text.casefold()
    contains_phone = 1 if _PHONE_RE.search(text) else 0
    contains_account = 1 if _ACCOUNT_RE.search(text) else 0
    contains_apk = 1 if any(h.casefold() in t_lower for h in APK_HINTS) else 0
    apk_outside_store = (
        1
        if contains_apk and any(h.casefold() in t_lower for h in OUTSIDE_STORE_HINTS)
        else (1 if contains_apk and url_is_shortener else 0)
    )

    permission_request_count = sum(
        1 for p in HIGH_RISK_PERMISSIONS if p.casefold() in t_lower
    )

    # 簡單綜合風險（規則；之後可換模型）
    risk = 0.0
    risk += 0.15 * contains_url
    risk += 0.20 * url_is_shortener
    risk += 0.15 * suspicious_tld
    risk += 0.10 * contains_phone
    risk += 0.15 * contains_account
    risk += 0.25 * contains_apk
    risk += 0.15 * apk_outside_store
    risk += min(0.30, 0.08 * permission_request_count)
    payload_risk_score = min(1.0, risk)

    return PayloadFeatures(
        contains_url=contains_url,
        url_is_shortener=url_is_shortener,
        suspicious_tld=suspicious_tld,
        contains_phone=contains_phone,
        contains_account=contains_account,
        contains_apk=contains_apk,
        apk_outside_store=apk_outside_store,
        permission_request_count=permission_request_count,
        payload_risk_score=payload_risk_score,
    )
