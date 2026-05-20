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


# --- 各子項 0 或 25（Track A B–E 類）---
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


def score_r_rules(text: str) -> RulesScoreResult:
    t = (text or "").strip()
    if not t:
        return RulesScoreResult(score=0, hits=[])

    hits: list[RuleHit] = []
    checks: list[tuple[str, int, tuple[str, ...]]] = [
        ("password_credentials", 25, _PWD),
        ("otp", 25, _OTP),
        ("card_bank_sensitive", 25, _CARD),
        ("national_id_ubn", 25, _ID),
        ("local_payment_pin", 25, _PAY_PIN),
        ("payment_ransom_threat", 25, _PAY_RANSOM),
    ]
    for rule_id, pts, pats in checks:
        q = _search(t, pats)
        if q:
            hits.append(RuleHit(rule_id=rule_id, points=pts, quote=q))

    score = _clamp(max((h.points for h in hits), default=0))
    return RulesScoreResult(score=score, hits=hits)


def rules_hits_to_dict(hits: list[RuleHit]) -> list[dict[str, Any]]:
    return [{"rule_id": h.rule_id, "points": h.points, "quote": h.quote} for h in hits]
