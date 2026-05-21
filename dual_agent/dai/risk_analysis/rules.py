"""Tier 1 硬規則：r_rules（0–100，取子項 max）。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RuleHit:
    rule_id: str
    points: int
    quote: str = ""


@dataclass
class RulesScoreResult:
    score: int
    hits: list[RuleHit] = field(default_factory=list)


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(n)))


def _search(text: str, patterns: tuple[str, ...]) -> str | None:
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(0)[:120]
    return None


def _has_any(text: str, patterns: tuple[str, ...]) -> bool:
    return _search(text, patterns) is not None


# --- 90：極高風險 ---
_PWD = (
    r"驗證.{0,6}密碼",
    r"確認.{0,6}密碼",
    r"更新.{0,6}密碼",
    r"變更.{0,6}密碼",
    r"請輸入.{0,6}密碼",
    r"請提供.{0,6}密碼",
    r"帳密",
    r"帳號密碼",
    r"登入密碼",
    r"網路?銀行.{0,6}密碼",
    r"網銀.{0,6}密碼",
)
_OTP = (
    r"驗證碼",
    r"一次性密碼",
    r"\bOTP\b",
    r"動態密碼",
    r"簡訊密碼",
)
_CARD = (
    r"信用卡",
    r"金融卡",
    r"銀聯卡",
    r"卡號",
    r"\bCVV\b",
    r"安全碼",
    r"到期日",
    r"匯款帳號",
    r"銀行帳號",
)
_ID = (
    r"身分證字號",
    r"身份證字號",
    r"身分證號",
    r"身份證號",
    r"國民身分證",
    r"統一編號",
    r"統編",
    r"報稅身分",
)
_PAY_PIN = (
    r"LINE\s*Pay",
    r"街口",
    r"JKOPAY",
    r"全支付",
    r"悠遊付",
    r"EasyWallet",
    r"一卡通\s*Money",
    r"台灣Pay",
    r"台灣\s*Pay",
    r"(LINE\s*Pay|街口|全支付|悠遊付|一卡通).{0,12}(PIN|密碼|交易密碼)",
)
_PAY_RANSOM = (
    r"匯款",
    r"轉帳",
    r"付款",
    r"繳費",
    r"贖金",
    r"勒索",
    r"綁架",
    r"否則.{0,8}(殺|報警|公開)",
    r"限時.{0,6}(匯|轉|付)",
    r"威脅",
    r"恐嚇",
)
_PHYSICAL_THREAT = (
    r"人身安全",
    r"傷害.{0,6}家人",
)

# --- 60：高風險組合 ---
_URL = (r"https?://", r"www\.", r"點擊.{0,6}連結", r"開啟.{0,6}連結")
_ACCOUNT_ANOMALY = (
    r"帳戶.{0,6}異常",
    r"銀行.{0,6}異常",
    r"帳戶.{0,6}凍結",
    r"停權",
    r"逾期未",
)
_URGENT_VERIFY = (
    r"立即.{0,6}驗證",
    r"馬上.{0,6}驗證",
    r"限時.{0,6}驗證",
    r"今日.{0,6}完成",
    r"請立即",
    r"請馬上",
)

# --- 25：低中風險 ---
_LOAN_SCAM = (
    r"借款",
    r"貸款",
    r"月計息",
    r"無擔保",
    r"免聯徵",
    r"代償高利",
    r"放款迅速",
    r"以月計息",
)
_NH_CARD_LOAN = (r"健保卡.{0,12}借", r"健保卡借款", r"以健保卡")
_UNSOLICITED_LOAN_PITCH = (
    r"電洽\s*[:：]?\s*09\d{8}",
    r"來電\s*[:：]?\s*09\d{8}",
    r"09\d{8}.{0,20}(林|先生|小姐|女士)",
)
_IDENTITY_SCAM = (
    r"實名認證",
    r"實名制",
    r"未辦理.{0,8}簽署",
    r"未.{0,6}辦理.{0,8}認證",
    r"政府補助",
    r"物流.{0,6}異常",
    r"包裹.{0,6}未取",
)
_LOW_FINANCE_NOTIFY = (
    r"金融",
    r"帳戶",
    r"通知",
    r"驗證",
    r"補助",
    r"繳款",
    r"帳單",
)


def score_r_rules(text: str) -> RulesScoreResult:
    t = (text or "").strip()
    if not t:
        return RulesScoreResult(score=0, hits=[])

    hits: list[RuleHit] = []

    tier90: list[tuple[str, int, tuple[str, ...]]] = [
        ("password_credentials", 90, _PWD),
        ("otp", 90, _OTP),
        ("card_bank_sensitive", 90, _CARD),
        ("national_id_ubn", 90, _ID),
        ("local_payment_pin", 90, _PAY_PIN),
        ("payment_ransom_threat", 90, _PAY_RANSOM),
        ("physical_threat", 90, _PHYSICAL_THREAT),
    ]
    for rule_id, pts, pats in tier90:
        q = _search(t, pats)
        if q:
            hits.append(RuleHit(rule_id=rule_id, points=pts, quote=q))

    if _has_any(t, _URL) and _has_any(t, _ACCOUNT_ANOMALY) and _has_any(t, _URGENT_VERIFY):
        parts = [_search(t, _URL), _search(t, _ACCOUNT_ANOMALY), _search(t, _URGENT_VERIFY)]
        quote = " + ".join(p for p in parts if p)[:120]
        hits.append(RuleHit(rule_id="high_risk_combo_link_account_urgent", points=60, quote=quote))

    tier25: list[tuple[str, int, tuple[str, ...]]] = [
        ("loan_scam", 25, _LOAN_SCAM),
        ("nh_card_loan", 25, _NH_CARD_LOAN),
        ("unsolicited_loan_pitch", 25, _UNSOLICITED_LOAN_PITCH),
        ("identity_scam_framework", 25, _IDENTITY_SCAM),
        ("low_finance_notify", 25, _LOW_FINANCE_NOTIFY),
    ]
    for rule_id, pts, pats in tier25:
        q = _search(t, pats)
        if q:
            hits.append(RuleHit(rule_id=rule_id, points=pts, quote=q))

    score = _clamp(max((h.points for h in hits), default=0))
    return RulesScoreResult(score=score, hits=hits)


def rules_hits_to_dict(hits: list[RuleHit]) -> list[dict[str, Any]]:
    return [{"rule_id": h.rule_id, "points": h.points, "quote": h.quote} for h in hits]
