"""外部證據：url_threat_hits、tls_findings（缺資料則不加分）。"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

from dual_agent.dai.user_db import extract_urls, normalize_domain


def build_url_threat_hits(
    urls: list[str],
    *,
    injected: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    若環境變數 `URL_THREAT_HITS_JSON` 為路徑或測試注入 `injected`，使用之；
    否則回傳每 URL 的 clean/unknown 占位（不給 LLM 猜惡意）。
    """
    if injected is not None:
        return list(injected)

    out: list[dict[str, Any]] = []
    target_urls = list(urls) if urls else extract_urls(" ".join(urls))
    for url in target_urls:
        out.append(
            {
                "url": url,
                "hits": {
                    "virustotal": False,
                    "phishtank": False,
                    "urlhaus": False,
                    "taiwan_165": False,
                    "telco_blocklist": False,
                },
                "vendor_count": 0,
                "label": "unknown",
            }
        )
    return out


def score_r_threat_intel(url_threat_hits: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """依 Track A A 項：僅用系統提供的 hits。"""
    evidence: list[dict[str, Any]] = []
    best = 0
    for row in url_threat_hits or []:
        if not isinstance(row, dict):
            continue
        hits = row.get("hits") if isinstance(row.get("hits"), dict) else {}
        vc = int(row.get("vendor_count") or 0)
        if vc <= 0 and hits:
            vc = sum(1 for v in hits.values() if v is True)
        label = str(row.get("label") or "").strip().lower()
        pts = 0
        if vc >= 5 and label in ("phishing", "malware"):
            pts = 40
        elif vc >= 4:
            pts = 35
        elif vc >= 2:
            pts = 25
        elif vc == 1:
            pts = 15
        if pts > best:
            best = pts
        if pts:
            evidence.append(
                {
                    "source": "url_threat_hits",
                    "url": row.get("url"),
                    "vendor_count": vc,
                    "label": label,
                    "points": pts,
                }
            )
    return max(0, min(100, best)), evidence


def build_tls_findings(
    urls: list[str],
    *,
    injected: list[dict[str, Any]] | None = None,
    probe: bool = False,
) -> list[dict[str, Any]]:
    if injected is not None:
        return list(injected)
    if not probe or os.environ.get("DAI_TLS_PROBE", "").strip().lower() not in ("1", "true", "yes"):
        return []
    # 輕量占位：預設不探測，避免測試／離線依賴網路
    return []


def score_r_tls(tls_findings: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    if not tls_findings:
        return 0, []
    best = 0
    evidence: list[dict[str, Any]] = []
    for row in tls_findings:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        pts = 0
        if row.get("self_signed") is True:
            pts = max(pts, 15)
        if row.get("domain_mismatch") is True:
            pts = max(pts, 15)
        if row.get("expired") is True:
            pts = max(pts, 10)
        if row.get("https") is False:
            pts = max(pts, 5)
        best = max(best, pts)
        if pts:
            evidence.append({"source": "tls_findings", "url": url, "points": pts, **row})
    return max(0, min(100, best)), evidence


def collect_missing_evidence(
    *,
    urls: list[str],
    url_threat_hits: list[dict[str, Any]],
    tls_findings: list[dict[str, Any]],
    sender_tech_context: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if urls and not url_threat_hits:
        missing.append("url_threat_hits")
    if urls and not tls_findings:
        missing.append("tls_findings")
    stc = sender_tech_context or {}
    if not stc or stc.get("route_type") in (None, "", "unknown") and not stc.get("sender_id_verified"):
        if urls or (stc.get("sender_display") or stc.get("sender_number")):
            missing.append("sender_tech_context")
    return missing
