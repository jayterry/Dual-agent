from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from dual_agent.cai.review_entry_eligibility import looks_like_declarative_sms_receipt_only


class InputOrigin(StrEnum):
    CHAT_BOX = "chat_box"
    SMS_SHARE = "sms_share"
    SMS_NOTIFICATION = "sms_notification"
    CLIPBOARD = "clipboard"
    WEB_SHARE = "web_share"
    APP_NOTIFICATION = "app_notification"
    MANUAL_IMPORT = "manual_import"
    UNKNOWN = "unknown"


class InputRole(StrEnum):
    INTENT = "intent"
    ARTIFACT = "artifact"
    MIXED = "mixed"
    SYSTEM_EVENT = "system_event"
    UNKNOWN = "unknown"


class ReviewScope(StrEnum):
    NONE = "none"
    ARTIFACT_ONLY = "artifact_only"
    RAW_INPUT = "raw_input"
    ARTIFACT_PLUS_INTENT = "artifact_plus_intent"


class DetectedTaskType(StrEnum):
    DIRECT_RESPONSE = "direct_response"
    ACTION = "action"
    CHECK = "check"
    MEMORY_UPDATE = "memory_update"
    UNKNOWN = "unknown"


class SenderType(StrEnum):
    PHONE_NUMBER = "phone_number"
    SHORT_CODE = "short_code"
    EMAIL = "email"
    APP = "app"
    URL = "url"
    UNKNOWN = "unknown"


class MessageChannel(StrEnum):
    SMS = "sms"
    NOTIFICATION = "notification"
    CLIPBOARD = "clipboard"
    SHARE_SHEET = "share_sheet"
    CHAT = "chat"
    EMAIL = "email"
    WEB = "web"
    UNKNOWN = "unknown"


@dataclass
class MessageSource:
    sender_id: str = ""
    sender_type: SenderType = SenderType.UNKNOWN
    source_app: str = ""
    channel: MessageChannel = MessageChannel.UNKNOWN
    received_at: str = ""
    is_known_contact: bool | None = None


@dataclass
class IngressEntities:
    urls: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    amounts: list[str] = field(default_factory=list)
    orgs: list[str] = field(default_factory=list)
    financial_terms: list[str] = field(default_factory=list)
    sensitive_terms: list[str] = field(default_factory=list)


@dataclass
class IngressPayload:
    raw_input_text: str
    input_origin: InputOrigin = InputOrigin.CHAT_BOX
    input_role: InputRole = InputRole.UNKNOWN
    intent_text: str = ""
    artifact_text: str = ""
    review_scope: ReviewScope = ReviewScope.NONE
    detected_task_type: DetectedTaskType = DetectedTaskType.UNKNOWN
    requires_dai: bool = False
    safety_relevant: bool = False
    message_source: MessageSource = field(default_factory=MessageSource)
    entities: IngressEntities = field(default_factory=IngressEntities)
    metadata: dict[str, Any] = field(default_factory=dict)


_URL_RE = re.compile(r"https?://[^\s<>\]）)\"'，。！？]+", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:(?:\+?\d[\d\s\-()]{6,}\d)|(?:\b\d{3,6}\b))")
_AMOUNT_RE = re.compile(
    r"(?:(?:NT\$|TWD\$|US\$|\$)\s?\d[\d,]*(?:\.\d+)?)|(?:\d[\d,]*(?:\.\d+)?\s*(?:元|塊|萬|萬元))",
    re.IGNORECASE,
)
_ORG_BRACKET_RE = re.compile(r"[【\[](.*?)[】\]]")
_ORG_KEYWORD_RE = re.compile(
    r"[\u4e00-\u9fffA-Za-z0-9]{2,20}(?:銀行|金控|證券|投信|保險|客服|警察|檢調|地檢署|法院|公司|App|APP)"
)
_REVIEW_INTENT_RE = re.compile(r"(幫我看|檢查|審查|審核|是不是詐騙|是否詐騙|風險|可疑|查詐騙)")
_ACTION_SEARCH_RE = re.compile(r"(搜尋|查詢|上網查|上網找|google|search)", re.IGNORECASE)
_GENERAL_CHAT_RE = (
    re.compile(r"^(你好|您好|嗨|哈囉|hello|hi)[!！。…\s]*$", re.IGNORECASE),
    re.compile(r"你(可以|能|會).{0,8}(做|幫).{0,8}(什麼|甚麼)"),
    re.compile(r"^我(是|叫)\s*[A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff .-]{0,30}$"),
    re.compile(r"^我現在在[\u4e00-\u9fffA-Za-z0-9 .-]{1,40}$"),
)
_MEMORY_UPDATE_RE = re.compile(r"(記住|幫我記住|請記得)")
_REVIEW_HELP_PATTERNS = (
    re.compile(r"有人發簡訊給(?:她|他|我|我們|家人)"),
    re.compile(r"有人傳訊息給(?:她|他|我|我們|家人)"),
    re.compile(r"(簡訊|訊息)內容很可怕"),
    re.compile(r"你可以幫我看看嗎"),
    re.compile(r"你不幫我看簡訊內容嗎"),
    re.compile(r"(?:被威脅|被恐嚇|有人威脅)"),
)
_THREAT_TERMS = (
    "威脅",
    "恐嚇",
    "綁架",
    "勒索",
    "贖金",
    "要給錢",
    "要匯款",
    "要付款",
    "殺",
    "小孩被綁架",
)
_THREAT_BODY_MARKERS = (
    "簡訊說",
    "訊息說",
    "內容說",
    "內容是",
    "他說",
    "她說",
    "對方說",
    "寫著",
    "除非",
    "不然就",
    "否則",
    "開始殺",
    "要我給",
    "給他",
    "給她",
    "給我",
    "匯款",
    "付款",
)

_FINANCIAL_TERMS = (
    "銀行",
    "帳戶",
    "账户",
    "金融",
    "信用卡",
    "轉帳",
    "转账",
    "匯款",
    "汇款",
    "付款",
    "投資",
    "投资",
    "報酬",
    "高報酬",
    "穩賺",
)
_SENSITIVE_TERMS = (
    "otp",
    "驗證碼",
    "验证码",
    "一次性密碼",
    "密碼",
    "密码",
    "登入",
    "登录",
    "login",
    "身分證",
    "身份证",
    "個資",
    "个资",
)
_RISK_EXTRA_TERMS = (
    "客服",
    "警察",
    "檢調",
    "检调",
    "apk",
    "下載",
    "下载",
    "安裝",
    "安装",
)


def _unique_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = (raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _coerce_str_enum(value: Any, enum_cls: type[StrEnum], default: StrEnum) -> StrEnum:
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except Exception:
        return default


def _normalize_message_source(message_source: MessageSource | None, origin: InputOrigin) -> MessageSource:
    src = message_source if isinstance(message_source, MessageSource) else MessageSource()
    sender_type = _coerce_str_enum(src.sender_type, SenderType, SenderType.UNKNOWN)
    channel = _coerce_str_enum(src.channel, MessageChannel, MessageChannel.UNKNOWN)
    if channel == MessageChannel.UNKNOWN:
        default_channel = {
            InputOrigin.CHAT_BOX: MessageChannel.CHAT,
            InputOrigin.SMS_SHARE: MessageChannel.SMS,
            InputOrigin.SMS_NOTIFICATION: MessageChannel.NOTIFICATION,
            InputOrigin.CLIPBOARD: MessageChannel.CLIPBOARD,
            InputOrigin.WEB_SHARE: MessageChannel.SHARE_SHEET,
            InputOrigin.APP_NOTIFICATION: MessageChannel.NOTIFICATION,
            InputOrigin.MANUAL_IMPORT: MessageChannel.UNKNOWN,
            InputOrigin.UNKNOWN: MessageChannel.UNKNOWN,
        }.get(origin, MessageChannel.UNKNOWN)
        channel = default_channel
    return MessageSource(
        sender_id=str(src.sender_id or "").strip(),
        sender_type=sender_type,
        source_app=str(src.source_app or "").strip(),
        channel=channel,
        received_at=str(src.received_at or "").strip(),
        is_known_contact=src.is_known_contact,
    )


def _contains_any(text: str, terms: tuple[str, ...]) -> list[str]:
    low = text.lower()
    hits = [term for term in terms if term.lower() in low]
    return _unique_keep_order(hits)


def _is_general_chat(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return any(p.search(t) for p in _GENERAL_CHAT_RE)


def _detect_task_type(text: str) -> DetectedTaskType:
    t = (text or "").strip()
    if not t:
        return DetectedTaskType.UNKNOWN
    if _MEMORY_UPDATE_RE.search(t):
        return DetectedTaskType.MEMORY_UPDATE
    if _ACTION_SEARCH_RE.search(t):
        return DetectedTaskType.ACTION
    if _REVIEW_INTENT_RE.search(t):
        return DetectedTaskType.CHECK
    if _is_general_chat(t):
        return DetectedTaskType.DIRECT_RESPONSE
    return DetectedTaskType.UNKNOWN


def _threat_term_hits(text: str) -> list[str]:
    return _contains_any(text, _THREAT_TERMS)


def _looks_like_threat_review_body(text: str, entities: IngressEntities) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    threat_hits = _threat_term_hits(t)
    if not threat_hits and not entities.amounts:
        return False
    if any(marker in t for marker in _THREAT_BODY_MARKERS):
        return True
    if entities.amounts and threat_hits:
        return True
    if len(t) >= 18 and threat_hits and any(tok in t for tok in ("要", "給", "匯", "付", "殺")):
        return True
    return False


def _looks_like_review_help_request(text: str, entities: IngressEntities) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _looks_like_threat_review_body(t, entities):
        return False
    if _looks_like_pure_review_intent(t):
        return True
    if any(p.search(t) for p in _REVIEW_HELP_PATTERNS):
        return True
    # 短句威脅求助：已有威脅語意，但還不像貼出正文
    threat_hits = _threat_term_hits(t)
    if threat_hits and len(t) <= 18 and not entities.amounts and not _URL_RE.search(t):
        return True
    if threat_hits and ("怎麼辦" in t or "幫我" in t or "看看" in t):
        return True
    return False


def _looks_like_pure_review_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if not _REVIEW_INTENT_RE.search(t):
        return False
    if ":" in t or "：" in t:
        return False
    if "\n" in t:
        return False
    if _URL_RE.search(t):
        return False
    if len(t) > 40:
        return False
    return True


def _split_chat_intent_and_artifact(text: str) -> tuple[str, str, str]:
    t = (text or "").strip()
    if not t:
        return "", "", ""
    for sep in ("：", ":"):
        if sep not in t:
            continue
        left, right = t.split(sep, 1)
        if _REVIEW_INTENT_RE.search(left) and right.strip():
            return left.strip(), right.strip(), "colon_intent_artifact"
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    if len(lines) >= 2 and _REVIEW_INTENT_RE.search(lines[0]):
        return lines[0], "\n".join(lines[1:]).strip(), "newline_intent_artifact"
    return "", "", ""


def extract_entities(text: str) -> IngressEntities:
    src = str(text or "")
    urls = _unique_keep_order(_URL_RE.findall(src))
    phones = _unique_keep_order(_PHONE_RE.findall(src))
    amounts = _unique_keep_order(_AMOUNT_RE.findall(src))
    orgs = _unique_keep_order(_ORG_BRACKET_RE.findall(src) + _ORG_KEYWORD_RE.findall(src))
    financial_terms = _contains_any(src, _FINANCIAL_TERMS)
    sensitive_terms = _contains_any(src, _SENSITIVE_TERMS)
    return IngressEntities(
        urls=urls,
        phones=phones,
        amounts=amounts,
        orgs=orgs,
        financial_terms=financial_terms,
        sensitive_terms=sensitive_terms,
    )


def _safety_relevance_from_entities(entities: IngressEntities, text: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if entities.urls:
        reasons.append("url")
    if entities.financial_terms:
        reasons.append("financial_terms")
    if entities.sensitive_terms:
        reasons.append("sensitive_terms")
    extra_hits = _contains_any(text, _RISK_EXTRA_TERMS)
    if extra_hits:
        reasons.append("risk_terms")
    return bool(reasons), _unique_keep_order(reasons)


def _ingress_payload_to_dict(payload: IngressPayload) -> dict[str, Any]:
    return asdict(payload)


def format_ingress_for_prompt(payload: IngressPayload, *, text_cap: int = 600) -> str:
    obj = _ingress_payload_to_dict(payload)
    for key in ("raw_input_text", "intent_text", "artifact_text"):
        val = str(obj.get(key) or "")
        if len(val) > text_cap:
            obj[key] = val[:text_cap] + "…（截斷）"
    return json.dumps(obj, ensure_ascii=False, indent=2)


def ingress_payload_to_dict(payload: IngressPayload) -> dict[str, Any]:
    return _ingress_payload_to_dict(payload)


def normalize_ingress(
    raw_input_text: str,
    input_origin: InputOrigin | str = "chat_box",
    optional_intent: str | None = None,
    message_source: MessageSource | None = None,
    metadata: dict[str, Any] | None = None,
) -> IngressPayload:
    raw = str(raw_input_text or "").strip()
    origin = _coerce_str_enum(input_origin, InputOrigin, InputOrigin.CHAT_BOX)
    src = _normalize_message_source(message_source, origin)
    meta: dict[str, Any] = dict(metadata or {})
    entities = extract_entities(raw)
    safety_relevant, safety_reasons = _safety_relevance_from_entities(entities, raw)
    if safety_reasons:
        meta["safety_reasons"] = list(safety_reasons)

    if origin in (InputOrigin.SMS_SHARE, InputOrigin.SMS_NOTIFICATION):
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.ARTIFACT,
            intent_text=(optional_intent or "請審查這則簡訊").strip(),
            artifact_text=raw,
            review_scope=ReviewScope.ARTIFACT_ONLY,
            detected_task_type=DetectedTaskType.CHECK,
            requires_dai=True,
            safety_relevant=True,
            message_source=src,
            entities=entities,
            metadata=meta,
        )

    if origin == InputOrigin.CHAT_BOX:
        split_intent, split_artifact, split_reason = _split_chat_intent_and_artifact(raw)
        if split_artifact:
            meta["split_reason"] = split_reason
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.MIXED,
                intent_text=split_intent,
                artifact_text=split_artifact,
                review_scope=ReviewScope.ARTIFACT_ONLY,
                detected_task_type=DetectedTaskType.CHECK,
                requires_dai=True,
                safety_relevant=True,
                message_source=src,
                entities=extract_entities(split_artifact),
                metadata=meta,
            )
        if looks_like_declarative_sms_receipt_only(raw, entities) and not _looks_like_threat_review_body(
            raw, entities
        ):
            meta["review_pending_candidate"] = True
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.INTENT,
                intent_text=raw,
                artifact_text="",
                review_scope=ReviewScope.NONE,
                detected_task_type=DetectedTaskType.CHECK,
                requires_dai=False,
                safety_relevant=True,
                message_source=src,
                entities=entities,
                metadata=meta,
            )
        if _looks_like_threat_review_body(raw, entities):
            meta["threat_review_candidate"] = True
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.ARTIFACT,
                intent_text=(optional_intent or "").strip(),
                artifact_text=raw,
                review_scope=ReviewScope.RAW_INPUT,
                detected_task_type=DetectedTaskType.CHECK,
                requires_dai=True,
                safety_relevant=True,
                message_source=src,
                entities=entities,
                metadata=meta,
            )
        if _looks_like_review_help_request(raw, entities):
            meta["review_pending_candidate"] = True
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.INTENT,
                intent_text=raw,
                artifact_text="",
                review_scope=ReviewScope.NONE,
                detected_task_type=DetectedTaskType.CHECK,
                requires_dai=False,
                safety_relevant=True,
                message_source=src,
                entities=entities,
                metadata=meta,
            )
        if _looks_like_pure_review_intent(raw):
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.INTENT,
                intent_text=raw,
                artifact_text="",
                review_scope=ReviewScope.NONE,
                detected_task_type=DetectedTaskType.CHECK,
                requires_dai=False,
                safety_relevant=True,
                message_source=src,
                entities=entities,
                metadata=meta,
            )
        detected = _detect_task_type(raw)
        if detected == DetectedTaskType.DIRECT_RESPONSE or _is_general_chat(raw):
            return IngressPayload(
                raw_input_text=raw,
                input_origin=origin,
                input_role=InputRole.INTENT,
                intent_text=raw,
                artifact_text="",
                review_scope=ReviewScope.NONE,
                detected_task_type=DetectedTaskType.DIRECT_RESPONSE,
                requires_dai=False,
                safety_relevant=False,
                message_source=src,
                entities=entities,
                metadata=meta,
            )
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.INTENT,
            intent_text=optional_intent or raw,
            artifact_text="",
            review_scope=ReviewScope.NONE,
            detected_task_type=detected,
            requires_dai=False,
            safety_relevant=safety_relevant,
            message_source=src,
            entities=entities,
            metadata=meta,
        )

    if safety_relevant:
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.ARTIFACT,
            intent_text=(optional_intent or "").strip(),
            artifact_text=raw,
            review_scope=ReviewScope.RAW_INPUT,
            detected_task_type=DetectedTaskType.CHECK,
            requires_dai=True,
            safety_relevant=True,
            message_source=src,
            entities=entities,
            metadata=meta,
        )

    detected = _detect_task_type(raw)
    if detected == DetectedTaskType.DIRECT_RESPONSE:
        return IngressPayload(
            raw_input_text=raw,
            input_origin=origin,
            input_role=InputRole.INTENT,
            intent_text=raw,
            artifact_text="",
            review_scope=ReviewScope.NONE,
            detected_task_type=DetectedTaskType.DIRECT_RESPONSE,
            requires_dai=False,
            safety_relevant=False,
            message_source=src,
            entities=entities,
            metadata=meta,
        )

    return IngressPayload(
        raw_input_text=raw,
        input_origin=origin,
        input_role=InputRole.UNKNOWN,
        intent_text=(optional_intent or "").strip(),
        artifact_text="",
        review_scope=ReviewScope.NONE,
        detected_task_type=DetectedTaskType.UNKNOWN,
        requires_dai=False,
        safety_relevant=False,
        message_source=src,
        entities=entities,
        metadata=meta,
    )
