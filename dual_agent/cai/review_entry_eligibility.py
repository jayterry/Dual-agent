"""
判斷「僅宣告收到簡訊／訊息、尚無可審正文」之輸入（結構模版，不依賴形容詞列舉）。

供 ingress、call_dai（meta-only artifact）共用，避免規則三處分裂。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dual_agent.ingress import IngressEntities


# 句式：可有可無主語「我／剛」＋收到＋可有量詞＋插入形容＋簡訊|訊息|通知＋可選句尾情緒
_SMS_RECEIPT_ONLY_RE = re.compile(
    r"^(我(剛|剛才)?)?收到(了)?(一封|一通|一則|一條|一個)?([\u4e00-\u9fff]{0,14})(簡訊|訊息)\s*[。．.!！？…,，\s]*([\u4e00-\u9fff]{0,12})?\s*$",
    re.UNICODE,
)
_SMS_RECEIPT_MOOD_RE = re.compile(
    r"^(我(剛|剛才)?)?(有人)?(傳|發)?(給我)?收到(了)?(一封|一通|一則|一條|一個)?"
    r"([\u4e00-\u9fff]{0,10})?(可疑|奇怪|怪怪|詭異)?(的)?(簡訊|訊息|通知)"
    r"([，,]?\s*[\u4e00-\u9fff]{0,14}(怪|奇怪|可疑|詭異|威脅))?\s*[。．.!！？…,，]*\s*$",
    re.UNICODE,
)
_REVIEW_INTENT_PHRASE_RE = re.compile(
    r"(簡訊|訊息|通知).{0,8}(怪|奇怪|可疑|詭異)|"
    r"有人(傳|發).{0,6}(簡訊|訊息)|"
    r"收到.{0,6}(可疑|奇怪).{0,4}(簡訊|訊息)|"
    r"你可以幫我(看看|看)嗎|"
    r"幫我看看這是不是詐騙|"
    r"幫我看(一下)?(這)?是不是詐騙",
    re.UNICODE,
)
_REVIEW_INTENT_ONLY_RE = re.compile(
    r"(幫我看|幫我看看|檢查|審查|審核|是不是詐騙|是否詐騙|查詐騙|可疑|有點怪)",
    re.IGNORECASE,
)
_MAX_META_DECLARATION_LEN = 64
_REVIEW_BLOCK = "【待審內容】"


def has_substantive_review_signals(raw: str, entities: IngressEntities) -> bool:
    """
    若輸入已包含可視為「待審本文」或其片段之訊號，則不重判為『僅收到宣告』。
    """
    t = (raw or "").strip()
    if not t:
        return False
    if _REVIEW_BLOCK in t:
        return True
    for sep in ("：", ":"):
        if sep not in t:
            continue
        left, right = t.split(sep, 1)
        if right.strip() and len(right.strip()) >= 6:
            from dual_agent.ingress import _REVIEW_INTENT_RE

            if _REVIEW_INTENT_RE.search(left):
                return True
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if len(lines) >= 2 and len(lines[1]) >= 6:
        from dual_agent.ingress import _REVIEW_INTENT_RE

        if _REVIEW_INTENT_RE.search(lines[0]):
            return True
    if len(t) > _MAX_META_DECLARATION_LEN:
        return True
    if entities.urls:
        return True
    if entities.amounts:
        return True
    if getattr(entities, "financial_terms", None):
        return True
    if getattr(entities, "sensitive_terms", None):
        return True
    if getattr(entities, "orgs", None):
        return True
    phones = getattr(entities, "phones", None) or ()
    for p in phones:
        digits = re.sub(r"\D", "", str(p))
        if len(digits) >= 8:
            return True
    if re.search(r"\d{5,}", t):
        return True
    low = t.lower()
    if "http://" in low or "https://" in low:
        return True
    return False


def looks_like_declarative_sms_receipt_only(raw: str, entities: IngressEntities) -> bool:
    """
    單句、符合「收到…簡訊／訊息」模版，且無實體／正文徵兆時，視為尚缺正文。
    """
    t = (raw or "").strip()
    if not t:
        return False
    if "\n" in t.strip():
        return False
    if len(t) > _MAX_META_DECLARATION_LEN:
        return False
    if has_substantive_review_signals(t, entities):
        return False
    compact = "".join(t.split())
    if _SMS_RECEIPT_ONLY_RE.match(compact) or _SMS_RECEIPT_MOOD_RE.match(compact):
        return True
    if _REVIEW_INTENT_PHRASE_RE.search(compact):
        return True
    return False


def _looks_like_pure_review_intent_no_body(raw: str) -> bool:
    t = (raw or "").strip()
    if not t or len(t) > 48:
        return False
    if ":" in t or "：" in t:
        return False
    if "\n" in t:
        return False
    if re.search(r"https?://", t, re.I):
        return False
    return bool(_REVIEW_INTENT_ONLY_RE.search(t))


def looks_like_review_intent_without_artifact(raw: str, entities: IngressEntities) -> bool:
    """
    審查意圖但尚無可審 artifact（應 review_pending_candidate，不可 call_dai）。
    """
    t = (raw or "").strip()
    if not t or has_substantive_review_signals(t, entities):
        return False
    if looks_like_declarative_sms_receipt_only(t, entities):
        return True
    if _looks_like_pure_review_intent_no_body(t):
        return True
    from dual_agent.ingress import extract_entities

    ents = entities if entities is not None else extract_entities(t)
    from dual_agent.ingress import (
        _looks_like_review_help_request,
        _looks_like_threat_review_body,
    )

    if _looks_like_threat_review_body(t, ents):
        return False
    if _looks_like_review_help_request(t, ents):
        return True
    return False


def artifact_meta_only_for_dai(artifact_text: str) -> bool:
    """
    Executor 側：將字串視為送往 DAI 的 artifact 時，是否為「尚無正文」占位。
    """
    from dual_agent.ingress import extract_entities

    t = str(artifact_text or "").strip()
    if not t:
        return True
    ents = extract_entities(t)
    if has_substantive_review_signals(t, ents):
        return False
    if looks_like_review_intent_without_artifact(t, ents):
        return True
    return False
