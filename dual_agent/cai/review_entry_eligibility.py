"""
判斷「僅宣告收到簡訊／訊息、尚無可審正文」之輸入（結構模版，不依賴形容詞列舉）。

供 ingress、call_dai（meta-only artifact）共用，避免規則三處分裂。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dual_agent.ingress import IngressEntities


# 句式：可有可無主語「我／剛」＋收到＋可有量詞＋至多 N 個漢字插入（情緒／形容）＋簡訊|訊息
_SMS_RECEIPT_ONLY_RE = re.compile(
    r"^(我(剛|剛才)?)?收到(了)?(一封|一通|一則|一條|一個)?([\u4e00-\u9fff]{0,14})(簡訊|訊息)\s*[。．.!！？…]*\s*$",
    re.UNICODE,
)
_MAX_META_DECLARATION_LEN = 48
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
    # 拆段：審査意圖 + 正文
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
    # 長文：不太可能是單句「收到簡訊」宣告
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
    return bool(_SMS_RECEIPT_ONLY_RE.match("".join(t.split())))


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
    if looks_like_declarative_sms_receipt_only(t, ents):
        return True
    return False
