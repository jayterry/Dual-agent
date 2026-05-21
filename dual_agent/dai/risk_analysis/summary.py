"""safety_summary 與機器分數一致性護欄。"""

from __future__ import annotations

from dual_agent.dai.risk_analysis.verdict import summary_indicates_scam


def _fallback_summary(score: int, verdict: str) -> str:
    return f"綜合風險 {score}/100，判定 {verdict}。"


_STRONG_SCAM_PHRASES = (
    "較高的詐騙風險",
    "高度詐騙",
    "極高風險",
    "明顯詐騙",
    "高度可疑",
    "可能涉及詐騙",
    "涉及詐騙",
)


def coherent_safety_summary(
    *,
    semantic_summary: str,
    risk_score: int,
    verdict: str,
    r_rules: int,
) -> str:
    """避免語意層寫高風險敘述但機器分數過低。"""
    if not semantic_summary:
        return _fallback_summary(risk_score, verdict)
    if r_rules >= 25 or risk_score >= 40:
        return semantic_summary
    if summary_indicates_scam(semantic_summary) and risk_score < 30:
        return _fallback_summary(risk_score, verdict)
    if any(p in semantic_summary for p in _STRONG_SCAM_PHRASES):
        return _fallback_summary(risk_score, verdict)
    return semantic_summary
