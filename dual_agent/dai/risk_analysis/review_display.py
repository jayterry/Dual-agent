"""送審結果：使用者面向的結構化顯示（風險分數／判定／主要原因／建議）。"""

from __future__ import annotations

import re
from typing import Any


_RULE_REASON_MAP: dict[str, str] = {
    "password_credentials": "要求提供或驗證密碼／帳密",
    "otp": "要求提供驗證碼或一次性密碼",
    "card_bank_sensitive": "索取銀行卡或金融卡敏感資訊",
    "national_id_ubn": "索取身分證或統編等個資",
    "local_payment_pin": "要求提供支付 App PIN 或交易密碼",
    "payment_ransom_threat": "涉及匯款、贖金或威脅付款",
    "physical_threat": "涉及人身安全威脅",
    "high_risk_combo_link_account_urgent": "同時出現連結、帳戶異常與急迫驗證",
    "loan_scam": "高額借款與低利率話術",
    "nh_card_loan": "以健保卡借款等不實貸款話術",
    "unsolicited_loan_pitch": "主動推銷貸款並留下聯絡方式",
    "identity_scam_framework": "實名認證或政府補助等冒充框架",
    "low_finance_notify": "金融或帳戶異常類通知用語",
}

_LABEL_REASON_MAP: dict[str, str] = {
    "financial_extortion": "涉及勒索或強迫付款",
    "payment_pressure": "施壓要求立即付款",
    "physical_threat": "涉及人身安全威脅",
    "credential_harvesting": "疑似索取帳號或驗證資料",
    "credential_harvest": "疑似索取帳號或驗證資料",
    "phishing": "疑似釣魚或假冒機構",
    "impersonation": "疑似冒充政府、銀行或物流",
    "malicious_link": "含可疑連結",
    "urgency_pressure": "使用急迫或威脅性語氣",
    "suspicious_notification": "可疑通知或推播訊息",
}

_SOURCE_REASON_PATTERNS: list[tuple[str, str]] = [
    (r"instagram|facebook|line_notify|notification|推播|通知", "來源為社群或 App 通知，非正式金融管道"),
    (r"android|ios|app", "來源為手機 App 通知"),
    (r"sms|簡訊", "來源為簡訊"),
]


def verdict_display(verdict: str) -> str:
    """顯示用判定（維持英文鍵，與計畫書一致）。"""
    v = (verdict or "allow").strip().lower()
    if v in ("block", "warn", "allow"):
        return v
    return "allow"


def _norm_label(raw: str) -> str:
    return str(raw).strip().lower().replace("-", "_")


def _text_signals(text: str) -> set[str]:
    t = (text or "").lower()
    out: set[str] = set()
    if re.search(r"line\s*pay|line\s*id|加\s*line|加入\s*line|line\s*：", t, re.I):
        out.add("line_contact")
    if re.search(r"貸款|借款|月計息|免擔保|免聯徵", t):
        out.add("loan_pitch")
    if re.search(r"https?://|www\.", t):
        out.add("has_url")
    if re.search(r"驗證碼|otp|一次性密碼", t, re.I):
        out.add("otp")
    if re.search(r"密碼|帳密", t):
        out.add("password")
    return out


def _source_reason(source: str) -> str | None:
    s = (source or "").strip().lower()
    if not s or s in ("desktop", "unknown"):
        return None
    for pat, msg in _SOURCE_REASON_PATTERNS:
        if re.search(pat, s, re.I):
            return msg
    if "." in s and "com." in s:
        return "來源為社群平台或 App 通知"
    return None


def build_user_reasons(
    *,
    text: str = "",
    rules_hits: list[dict[str, Any]] | None = None,
    labels: list[str] | None = None,
    source: str = "",
    urls: list[str] | None = None,
    r_threat_intel: int = 0,
    r_tls: int = 0,
    limit: int = 6,
) -> list[str]:
    """人話主要原因（不含 DAG 步驟名、不含分數）。"""
    out: list[str] = []
    seen: set[str] = set()

    def add(msg: str) -> None:
        s = str(msg or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s[:160])

    for hit in rules_hits or []:
        if not isinstance(hit, dict):
            continue
        rid = str(hit.get("rule_id") or "").strip()
        add(_RULE_REASON_MAP.get(rid, ""))

    for raw in labels or []:
        lbl = _norm_label(raw)
        add(_LABEL_REASON_MAP.get(lbl, ""))

    for sig, msg in (
        ("line_contact", "要求加入 LINE 或私下通訊軟體聯絡"),
        ("loan_pitch", "高額借款與低利率話術"),
        ("otp", "要求提供驗證碼"),
        ("password", "要求提供密碼或帳密"),
        ("has_url", "訊息含有連結"),
    ):
        if sig in _text_signals(text):
            add(msg)

    src_msg = _source_reason(source)
    if src_msg:
        add(src_msg)

    if int(r_threat_intel or 0) >= 15:
        add("連結或網址命中威脅情資")
    if int(r_tls or 0) > 0:
        add("連結的 TLS 或憑證異常")
    if urls and not any("連結" in x for x in out):
        add("訊息含有連結")

    if not out:
        add("內容具有可疑推銷或異常要求特徵")

    return out[:limit]


def build_user_suggestions(
    *,
    verdict: str,
    rules_hits: list[dict[str, Any]] | None = None,
    labels: list[str] | None = None,
    text: str = "",
    recommended_action: str = "",
    limit: int = 5,
) -> list[str]:
    """使用者建議條列（與主要原因分開）。"""
    out: list[str] = []
    seen: set[str] = set()
    v = verdict_display(verdict)
    action = (recommended_action or "").strip().lower()
    hits = {str(h.get("rule_id") or "") for h in (rules_hits or []) if isinstance(h, dict)}
    label_set = {_norm_label(x) for x in (labels or [])}
    sigs = _text_signals(text)

    def add(msg: str) -> None:
        s = str(msg or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s[:160])

    if v == "block" or action == "block":
        add("建議阻擋，勿點擊連結、勿匯款或提供個資")
    elif v == "warn" or action == "ask_user":
        add("請提高警覺，勿輕信來路不明訊息")

    if "line_contact" in sigs or re.search(r"line", text, re.I):
        add("不要加入 LINE 或私下通訊管道聯絡")
    if hits & {"password_credentials", "otp", "card_bank_sensitive", "national_id_ubn", "local_payment_pin"}:
        add("不要提供身分證、帳戶、密碼或驗證碼")
    elif "password" in sigs or "otp" in sigs:
        add("不要提供身分證、帳戶或驗證碼")
    if hits & {"loan_scam", "nh_card_loan", "unsolicited_loan_pitch"} or "loan_pitch" in sigs:
        add("若有資金需求，請透過合法金融機構官方管道確認")
    if label_set & {"phishing", "impersonation", "malicious_link"} or "has_url" in sigs:
        add("不要點擊訊息中的連結")
    if label_set & {"financial_extortion", "payment_pressure"} or hits & {"payment_ransom_threat"}:
        add("不要依指示匯款或付款")

    if v == "allow" and action == "continue" and len(out) < 2:
        add("分數偏低仍請留意來路，若有疑慮請向官方管道查證")

    if not out:
        add("若有疑慮，請向官方或原服務管道查證後再回應")

    return out[:limit]


def format_review_display(
    *,
    risk_score: int,
    verdict: str,
    reasons: list[str],
    suggestions: list[str],
) -> str:
    """組成送審／App 共用之多行文字。"""
    lines = [
        f"風險分數：{int(risk_score)}/100",
        f"判定：{verdict_display(verdict)}",
        "",
        "主要原因：",
    ]
    for r in reasons:
        lines.append(f"• {r}")
    lines.append("")
    lines.append("建議：")
    for s in suggestions:
        lines.append(f"• {s}")
    return "\n".join(lines).strip()


def brief_safety_line(risk_score: int, verdict: str) -> str:
    """與最終分數一致的一句摘要（供 safety_summary / archive）。"""
    v = verdict_display(verdict)
    if v == "block":
        return f"綜合風險 {int(risk_score)}/100，判定 {v}，建議勿輕信並避免操作。"
    if v == "warn":
        return f"綜合風險 {int(risk_score)}/100，判定 {v}，請提高警覺並查證來源。"
    return f"綜合風險 {int(risk_score)}/100，判定 {v}，仍請留意來路。"


def enrich_report_display_fields(
    report: dict[str, Any],
    *,
    text: str = "",
    source: str = "",
) -> dict[str, Any]:
    """在 report 上附加 user_reason_highlights、user_suggestions、display_text。"""
    rules_hits = list((report.get("track_a") or {}).get("matched_rules") or [])
    labels = list(report.get("labels") or [])
    cs = dict(report.get("component_scores") or {})
    urls = list((report.get("analysis_payload") or {}).get("urls") or [])
    risk_score = int(report.get("risk_score") or 0)
    verdict = str(report.get("verdict") or "allow")
    action = str(report.get("recommended_cai_action") or "continue")

    reasons = build_user_reasons(
        text=text,
        rules_hits=rules_hits,
        labels=labels,
        source=source,
        urls=urls,
        r_threat_intel=int(cs.get("r_threat_intel") or 0),
        r_tls=int(cs.get("r_tls") or 0),
    )
    suggestions = build_user_suggestions(
        verdict=verdict,
        rules_hits=rules_hits,
        labels=labels,
        text=text,
        recommended_action=action,
    )
    display_text = format_review_display(
        risk_score=risk_score,
        verdict=verdict,
        reasons=reasons,
        suggestions=suggestions,
    )
    report["user_reason_highlights"] = reasons
    report["user_suggestions"] = suggestions
    report["display_text"] = display_text
    report["safety_summary"] = brief_safety_line(risk_score, verdict)
    return report
