"""DAI UEBA：使用者行為／來源／信任網域（userDB，JSON 持久化）。"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from dual_agent.logutil import get_logger

log = get_logger("dai.user_db")

_LOCK = threading.Lock()
_URL_RE = re.compile(r"https?://[^\s<>\]）)\"'，。！？]+", re.IGNORECASE)


def _default_path() -> str:
    return os.environ.get("USER_DB_PATH", "").strip() or os.path.join(os.getcwd(), "user_profile_db.json")


def _load_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001
        log.error("讀取 userDB 失敗 path=%s err=%s", path, e)
        return {}


def _save_json(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _now_ts() -> float:
    return float(time.time())


def _norm_source(source: Optional[str]) -> str:
    s = (source or "").strip().lower()
    return s or "unknown"


def normalize_domain(url_or_host: str) -> str:
    raw = (url_or_host or "").strip().lower()
    if not raw:
        return ""
    if "://" in raw:
        try:
            host = urlparse(raw).hostname or ""
        except Exception:  # noqa: BLE001
            host = raw
    else:
        host = raw.split("/")[0].split("?")[0]
    host = host.strip().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def extract_urls(text: str) -> list[str]:
    return _unique_keep_order(_URL_RE.findall(text or ""))


def _unique_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        s = (x or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _ensure_schema(db: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(db, dict):
        db = {}
    db.setdefault("sources", {})
    db.setdefault("trusted_domains", {})
    db.setdefault("blocked_domains", {})
    db.setdefault("categories", {})
    db.setdefault(
        "temporal",
        {"hour_hist": [0] * 24, "last_burst": {"window_s": 3600, "count": 0, "started_at": 0.0}},
    )
    db.setdefault(
        "actions",
        {"url_seen_count": 0, "otp_seen_count": 0, "apk_seen_count": 0, "money_terms_count": 0},
    )
    return db


def _get_source(db: dict[str, Any], source: str) -> dict[str, Any]:
    sources = db.get("sources")
    if not isinstance(sources, dict):
        sources = {}
        db["sources"] = sources
    src = sources.get(source)
    if not isinstance(src, dict):
        src = {}
        sources[source] = src
    src.setdefault("trust_status", "UNKNOWN")
    src.setdefault("seen_count", 0)
    src.setdefault("first_seen_at", 0.0)
    src.setdefault("last_seen_at", 0.0)
    return src


def _get_domain_bucket(db: dict[str, Any], key: str, *, blocked: bool) -> dict[str, Any]:
    name = "blocked_domains" if blocked else "trusted_domains"
    bucket = db.get(name)
    if not isinstance(bucket, dict):
        bucket = {}
        db[name] = bucket
    row = bucket.get(key)
    if not isinstance(row, dict):
        row = {}
        bucket[key] = row
    return row


def is_domain_trusted(domain: str, path: Optional[str] = None) -> bool:
    key = normalize_domain(domain)
    if not key:
        return False
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        trusted = db.get("trusted_domains")
        blocked = db.get("blocked_domains")
    if isinstance(blocked, dict) and key in blocked:
        return False
    return isinstance(trusted, dict) and key in trusted


def is_domain_blocked(domain: str, path: Optional[str] = None) -> bool:
    key = normalize_domain(domain)
    if not key:
        return False
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        blocked = db.get("blocked_domains")
    return isinstance(blocked, dict) and key in blocked


def list_trusted_domains(*, path: Optional[str] = None) -> list[str]:
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        trusted = db.get("trusted_domains")
    if not isinstance(trusted, dict):
        return []
    return sorted(str(k) for k in trusted.keys() if str(k).strip())


def mark_trusted_domain(*, domain: str, path: Optional[str] = None) -> dict[str, Any]:
    key = normalize_domain(domain)
    if not key:
        return {"ok": False, "error": "empty_domain"}
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        row = _get_domain_bucket(db, key, blocked=False)
        row["trusted_at"] = _now_ts()
        blocked = db.get("blocked_domains")
        if isinstance(blocked, dict):
            blocked.pop(key, None)
        _save_json(p, db)
    return {"ok": True, "domain": key}


def mark_blocked_domain(*, domain: str, path: Optional[str] = None) -> dict[str, Any]:
    key = normalize_domain(domain)
    if not key:
        return {"ok": False, "error": "empty_domain"}
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        row = _get_domain_bucket(db, key, blocked=True)
        row["blocked_at"] = _now_ts()
        trusted = db.get("trusted_domains")
        if isinstance(trusted, dict):
            trusted.pop(key, None)
        _save_json(p, db)
    return {"ok": True, "domain": key}


def remove_trusted_domain(*, domain: str, path: Optional[str] = None) -> dict[str, Any]:
    key = normalize_domain(domain)
    if not key:
        return {"ok": False, "error": "empty_domain"}
    p = path or _default_path()
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        trusted = db.get("trusted_domains")
        if isinstance(trusted, dict):
            trusted.pop(key, None)
        _save_json(p, db)
    return {"ok": True, "domain": key}


def build_trusted_urls(text: str, *, path: Optional[str] = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for url in extract_urls(text):
        dom = normalize_domain(url)
        if not dom:
            continue
        out.append(
            {
                "url": url,
                "domain": dom,
                "trusted": is_domain_trusted(dom, path=path),
                "blocked": is_domain_blocked(dom, path=path),
            }
        )
    return out


def record_seen(*, source: str, path: Optional[str] = None) -> int:
    p = path or _default_path()
    key = _norm_source(source)
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        now = _now_ts()
        src = _get_source(db, key)
        src["seen_count"] = int(src.get("seen_count") or 0) + 1
        src["last_seen_at"] = now
        if float(src.get("first_seen_at") or 0.0) <= 0.0:
            src["first_seen_at"] = now
        _save_json(p, db)
        return int(src["seen_count"])


def _contains_sensitive_actions(text: str) -> dict[str, bool]:
    t = (text or "").lower()
    return {
        "has_url": ("http://" in t) or ("https://" in t) or ("www." in t),
        "has_otp": any(x in t for x in ("otp", "驗證碼", "一次性密碼")),
        "has_apk": any(x in t for x in ("apk", "安裝", "下載")),
        "has_money": any(x in t for x in ("匯款", "轉帳", "付款", "刷卡", "繳費")),
    }


def update_observation(
    *,
    text: str,
    source: str,
    path: Optional[str] = None,
) -> dict[str, Any]:
    p = path or _default_path()
    key = _norm_source(source)
    flags = _contains_sensitive_actions(text)
    with _LOCK:
        db = _ensure_schema(_load_json(p))
        src = _get_source(db, key)
        if flags["has_url"]:
            src["url_seen_count"] = int(src.get("url_seen_count") or 0) + 1
        actions = db.get("actions")
        if isinstance(actions, dict) and flags["has_url"]:
            actions["url_seen_count"] = int(actions.get("url_seen_count") or 0) + 1
        _save_json(p, db)
    return {"ok": True, "source": key, "flags": flags}


@dataclass(frozen=True)
class UserRisk:
    s_user_0_100: int
    delta_user: int
    need_user_confirm: bool
    reasons: list[str]
    source_key: str
    trusted: bool
    blocked: bool
    seen_count: int
    trust_status: str
    trusted_urls: list[dict[str, Any]]
    all_urls_trusted: bool


def compute_user_risk(
    *,
    text: str,
    source: Optional[str],
    llm_verdict: str,
    risk_total_fused: int,
    path: Optional[str] = None,
) -> UserRisk:
    p = path or _default_path()
    key = _norm_source(source)
    t = (text or "").strip().lower()
    trusted_urls = build_trusted_urls(text, path=p)

    with _LOCK:
        db = _ensure_schema(_load_json(p))
        src = _get_source(db, key)
        trust_status = str(src.get("trust_status") or "UNKNOWN").upper()
        seen_count = int(src.get("seen_count") or 0)

    reasons: list[str] = []
    s_user = 0
    delta = 0
    need_confirm = False

    if trust_status == "BLOCKED":
        reasons.append("source.trust_status=BLOCKED(+15)")
        s_user = 95
        delta = 15
    elif trust_status == "TRUSTED":
        reasons.append("source.trust_status=TRUSTED(-15)")
        s_user = 10
        delta = -15
    else:
        if seen_count <= 1:
            reasons.append("source.new_or_rare")
            s_user += 70
            delta += 6
            need_confirm = True
        else:
            reasons.append("source.seen_before_unknown")
            s_user += 40
            delta += 2

    sensitive_terms = (
        "http://",
        "https://",
        "otp",
        "驗證碼",
        "匯款",
        "轉帳",
        "付款",
        "下載",
        "apk",
        "連結",
    )
    if any(x in t for x in sensitive_terms):
        reasons.append("actions.contains_sensitive_terms")
        s_user = min(100, s_user + 15)
        delta = min(15, delta + 5)
        need_confirm = True

    # 網域維度（信任網站 UEBA）
    url_rows = [u for u in trusted_urls if u.get("domain")]
    if url_rows:
        any_blocked = any(bool(u.get("blocked")) for u in url_rows)
        all_trusted = all(bool(u.get("trusted")) for u in url_rows)
        any_unknown = any(not u.get("trusted") and not u.get("blocked") for u in url_rows)

        if any_blocked:
            reasons.append("domain.blocked_in_message(+8)")
            s_user = min(100, s_user + 20)
            delta = min(15, delta + 8)
            need_confirm = False
        elif all_trusted and len(url_rows) > 0:
            reasons.append("domain.all_urls_trusted(-6)")
            s_user = max(0, s_user - 10)
            delta = max(-15, delta - 6)
        elif any_unknown:
            reasons.append("domain.unknown_url_present")
            s_user = min(100, s_user + 10)
            delta = min(15, delta + 3)
            need_confirm = True

    all_urls_trusted = bool(url_rows) and all(bool(u.get("trusted")) for u in url_rows)

    if str(llm_verdict).lower() == "block" or int(risk_total_fused) >= 85:
        if delta < 0:
            reasons.append("guardrail_no_downrank")
            delta = 0
        need_confirm = False

    s_user = int(max(0, min(100, s_user)))
    delta = int(max(-15, min(15, delta)))

    return UserRisk(
        s_user_0_100=s_user,
        delta_user=delta,
        need_user_confirm=bool(need_confirm),
        reasons=reasons,
        source_key=key,
        trusted=trust_status == "TRUSTED",
        blocked=trust_status == "BLOCKED",
        seen_count=seen_count,
        trust_status=trust_status,
        trusted_urls=trusted_urls,
        all_urls_trusted=all_urls_trusted,
    )


def user_risk_to_report_dict(ur: UserRisk, *, source: Optional[str], risk_total_fused: int) -> dict[str, Any]:
    fused_user = int(max(0, min(100, int(risk_total_fused) + int(ur.delta_user))))
    return {
        "source": (source or "unknown").strip() or "unknown",
        "source_key": ur.source_key,
        "seen_count": ur.seen_count,
        "trusted": ur.trusted,
        "blocked": ur.blocked,
        "trust_status": ur.trust_status,
        "s_user": ur.s_user_0_100,
        "delta_user": ur.delta_user,
        "need_user_confirm": ur.need_user_confirm,
        "reasons": list(ur.reasons),
        "trusted_urls": list(ur.trusted_urls),
        "all_urls_trusted": ur.all_urls_trusted,
        "risk_total_user_fused": fused_user,
    }


def apply_ueba_to_report(
    report_dict: dict[str, Any],
    *,
    text: str,
    source: Optional[str],
    path: Optional[str] = None,
) -> dict[str, Any]:
    """將 UEBA 寫入 guard report（Phase4）。"""
    src = (source or "unknown").strip() or "unknown"
    record_seen(source=src, path=path)
    update_observation(text=text, source=src, path=path)

    fusion = report_dict.get("risk_fusion") if isinstance(report_dict.get("risk_fusion"), dict) else {}
    risk_fused = int(report_dict.get("risk_score_total_fused") or fusion.get("risk_total") or report_dict.get("risk_score_total") or 0)
    verdict = str(report_dict.get("verdict") or "")

    ur = compute_user_risk(
        text=text,
        source=src,
        llm_verdict=verdict,
        risk_total_fused=risk_fused,
        path=path,
    )
    report_dict["risk_user"] = user_risk_to_report_dict(ur, source=src, risk_total_fused=risk_fused)
    report_dict["risk_score_total_user_fused"] = int(report_dict["risk_user"]["risk_total_user_fused"])
    return report_dict


def enrich_dai_payload_with_ueba(
    dai_payload: dict[str, Any],
    *,
    text: str,
    source: Optional[str],
    path: Optional[str] = None,
) -> dict[str, Any]:
    """call_dai 完成後補上 risk_user（供 Replan / App）。"""
    src = (source or "unknown").strip() or "unknown"
    record_seen(source=src, path=path)
    update_observation(text=text, source=src, path=path)

    risk_score = int(dai_payload.get("risk_score") or 0)
    verdict = "block" if risk_score >= 85 else ("quarantine" if risk_score >= 70 else "allow")

    ur = compute_user_risk(
        text=text,
        source=src,
        llm_verdict=verdict,
        risk_total_fused=risk_score,
        path=path,
    )
    risk_user = user_risk_to_report_dict(ur, source=src, risk_total_fused=risk_score)
    dai_payload = dict(dai_payload)
    dai_payload["risk_user"] = risk_user
    dai_payload["risk_score_user_fused"] = int(risk_user["risk_total_user_fused"])
    dai_payload["trusted_urls"] = list(risk_user.get("trusted_urls") or [])
    return dai_payload
