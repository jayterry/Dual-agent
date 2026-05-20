"""verdict 與 dominant_source。"""

from __future__ import annotations

from typing import Any


def verdict_from_score(score: int) -> str:
    s = int(score)
    if s >= 85:
        return "block"
    if s >= 70:
        return "warn"
    return "allow"


def dominant_source(component_scores: dict[str, int]) -> str:
    if not component_scores:
        return "none"
    return max(component_scores.items(), key=lambda kv: kv[1])[0]


def apply_ueba_to_display_score(
    r_final: int,
    *,
    delta_user: int,
    r_rules: int,
    r_threat_intel: int,
) -> int:
    """UEBA 調整顯示分；高可信惡意證據不得被完全洗掉。"""
    base = int(r_final)
    adjusted = max(0, min(100, base + int(delta_user)))
    floor = max(r_rules, r_threat_intel)
    if floor >= 85:
        return max(adjusted, floor, base)
    if base >= 85:
        return max(adjusted, base)
    return adjusted


def recommended_cai_action(verdict: str, risk_score: int) -> str:
    v = (verdict or "").strip().lower()
    if v == "block" or risk_score >= 85:
        return "block"
    if v == "warn" or risk_score >= 70:
        return "ask_user"
    return "continue"
