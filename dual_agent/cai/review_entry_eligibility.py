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
_WEATHER_RE = re.compile(r"(天氣|氣溫|降雨|颱風|風力)")
_OPEN_WITH_URL_RE = re.compile(r"(開|打開|開啟).{0,16}https?://", re.IGNORECASE)
_COMPOUND_THEN_OPEN_RE = re.compile(r"(再|順便|然後).{0,12}(幫我)?(開|打開|開啟)")
_PHISHING_CTA_RE = re.compile(r"(點擊|點選).{0,24}(連結|驗證|登入|完成)")


_LINK_SAFETY_REVIEW_RE = re.compile(
    r"(安不安全|有沒有風險|有風險嗎|危不危險|是不是詐騙|是否詐騙|可不可信|能不能點|要不要點)",
    re.IGNORECASE,
)


def _urls_imply_review_body(raw: str, entities: IngressEntities) -> bool:
    """URL 單獨不足以升格送審；需搭配審查意圖、金融／釣魚等訊號。"""
    if not getattr(entities, "urls", None):
        return False
    t = (raw or "").strip()
    if getattr(entities, "financial_terms", None):
        return True
    if getattr(entities, "sensitive_terms", None):
        return True
    if _PHISHING_CTA_RE.search(t):
        return True
    if _REVIEW_INTENT_ONLY_RE.search(t) or _LINK_SAFETY_REVIEW_RE.search(t):
        return True
    if re.search(r"[【\[][^】\]]{1,24}[】\]]", t):
        return True
    return False


def looks_like_action_workflow(raw: str, entities: IngressEntities) -> bool:
    """
    複合工作指令（搜尋／天氣／開連結等）：句中即使有 URL 也不應整句升格為防詐送審。
    """
    t = (raw or "").strip()
    if not t:
        return False

    from dual_agent.cai.planner_context import (
        explicit_web_search_requested,
        open_site_requested,
    )
    from dual_agent.ingress import (
        _ACTION_SEARCH_RE,
        _REVIEW_INTENT_RE,
        _looks_like_threat_review_body,
    )

    if _REVIEW_INTENT_RE.search(t) or _REVIEW_INTENT_ONLY_RE.search(t):
        return False
    if re.search(r"(是不是|是否).{0,8}詐騙", t):
        return False
    if _looks_like_threat_review_body(t, entities):
        return False
    if entities.financial_terms or entities.sensitive_terms:
        return False
    if _PHISHING_CTA_RE.search(t):
        return False
    if re.search(r"[【\[][^】\]]{1,24}[】\]]", t) and entities.urls:
        if not open_site_requested(t) and not _ACTION_SEARCH_RE.search(t):
            return False

    has_action = (
        bool(_ACTION_SEARCH_RE.search(t))
        or explicit_web_search_requested(t)
        or open_site_requested(t)
        or bool(_WEATHER_RE.search(t))
    )
    if not has_action:
        return False

    if entities.urls:
        return (
            open_site_requested(t)
            or bool(_OPEN_WITH_URL_RE.search(t))
            or bool(_COMPOUND_THEN_OPEN_RE.search(t))
            or (
                bool(_WEATHER_RE.search(t))
                and (
                    bool(_OPEN_WITH_URL_RE.search(t))
                    or bool(_COMPOUND_THEN_OPEN_RE.search(t))
                )
            )
            or (
                bool(_ACTION_SEARCH_RE.search(t))
                and bool(_COMPOUND_THEN_OPEN_RE.search(t))
            )
        )

    return True


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
    if _urls_imply_review_body(t, entities):
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


_REVIEW_DECLINE_RE = re.compile(
    r"(不要|沒有要|沒有|不想|不用|不必|別|勿).{0,16}(看|審|審查|查|貼|給你看).{0,10}(簡訊|訊息|短信)|"
    r"(不要再|不用再去|不用再).{0,10}(問|要|提).{0,10}(簡訊|訊息)|"
    r"不用審(了|查)?|不要審(了|查)?|算了.{0,8}(不要|別)",
    re.UNICODE,
)
_SHORT_AFFIRMATIVE_PIVOT_RE = re.compile(
    r"^(可以|好|好的|OK|Ok|行|沒問題)[!！。…\s]*$",
    re.I,
)
_LOCATION_ONLY_RE = re.compile(
    r"^(台灣)?(台北|台中|高雄|新北|桃園|台南|基隆|新竹|嘉義|屏東|宜蘭|花蓮|台東|澎湖|金門|馬祖)(市|縣)?$",
    re.UNICODE,
)


def looks_like_review_declined(raw: str) -> bool:
    """使用者明確拒絕送審／不要再問簡訊。"""
    t = (raw or "").strip()
    if not t:
        return False
    return bool(_REVIEW_DECLINE_RE.search(t))


def looks_like_short_affirmative_pivot(raw: str) -> bool:
    """待審後短肯定，常接續助理剛提議的任務（如查天氣）。"""
    t = (raw or "").strip()
    if not t:
        return False
    return bool(_SHORT_AFFIRMATIVE_PIVOT_RE.match(t))


def looks_like_location_for_weather(raw: str) -> bool:
    """純地名，作為天氣查詢參數補充。"""
    t = (raw or "").strip()
    if not t:
        return False
    return bool(_LOCATION_ONLY_RE.match(t))


def should_abandon_pending_review(
    raw: str,
    *,
    ingress_artifact_text: str = "",
    pending_review: bool = False,
) -> bool:
    """
    待審中是否應放棄送審、改走新任務或 direct_response。
    供 plan_execute / validate 在 LLM 規劃前後同步狀態與底線校正。
    """
    if not pending_review:
        return False
    if (ingress_artifact_text or "").strip():
        return False
    t = (raw or "").strip()
    if not t:
        return False
    if looks_like_review_declined(t):
        return True
    if looks_like_short_affirmative_pivot(t):
        return True
    if looks_like_location_for_weather(t):
        return True
    if len(t) <= 48 and _WEATHER_RE.search(t):
        return True
    from dual_agent.ingress import extract_entities

    if looks_like_action_workflow(t, extract_entities(t)):
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
