"""
Deterministic 複合句語意路由（沙盒模組）。

將「子句切分 → 受詞優先 skill 選擇 → 參數抽取」編碼為可測規則；
高信心時於 Planner validate 之後覆寫 todos（見 apply_semantic_router）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final, Literal

from dual_agent.cai.planner_context import (
    resolve_open_url_from_user_text,
    strip_planner_system_prefix,
)
from dual_agent.cai.schemas import PlanStep

Confidence = Literal["high", "low", "none"]

_WEATHER_OBJECT: Final[re.Pattern[str]] = re.compile(
    r"(天氣|氣溫|降雨|颱風|風力|會不會下雨|下不下雨)",
)
_WEATHER_LOCATION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"([\u4e00-\u9fff]{2,4})(今天|明天|後天|后天)?(的)?(天氣|氣溫|降雨|颱風|風力)"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(今天|明天|後天|后天)會不會下雨"),
    re.compile(r"([\u4e00-\u9fff]{2,4})會不會下雨"),
    re.compile(r"([\u4e00-\u9fff]{2,4})(今天|明天|後天|后天)下不下雨"),
)
_OPEN_VERB: Final[re.Pattern[str]] = re.compile(
    r"(打開|開啟|開一下|啟動|進入|開|open|launch)",
    re.IGNORECASE,
)
_SEARCH_PREFIX: Final[re.Pattern[str]] = re.compile(
    r"^(搜尋|幫我搜|查詢|幫我查|上網查|上網找|上網搜|網路上查|查一下|查)\s*",
)
_GOOGLE_SEARCH: Final[re.Pattern[str]] = re.compile(
    r"(用|以|在)?\s*(google|谷歌)\s*(搜|查|找|一下)",
    re.IGNORECASE,
)
_TEMPORAL_SUFFIX: Final[tuple[str, ...]] = ("即時", "今天", "明天", "後天", "后天")
_DEICTIC: Final[re.Pattern[str]] = re.compile(
    r"(我喜歡的|喜歡的遊戲|剛剛那個|前面那則|那一款|那個遊戲|那款遊戲)",
)
_FETCH_INTENT: Final[re.Pattern[str]] = re.compile(
    r"(讀|閱讀|摘要|核對|看看).{0,80}(內容|正文|網頁|頁面)|"
    r"(讀|閱讀).{0,80}https?://|"
    r"https?://.{0,40}(幫我摘要|摘要)",
    re.IGNORECASE,
)
_REVIEW_INTENT: Final[re.Pattern[str]] = re.compile(
    r"(幫我看|幫我看看|檢查|審查).{0,12}(是不是|是否).{0,8}詐騙|"
    r"(是不是|是否).{0,8}詐騙|幫我看.*詐騙",
    re.IGNORECASE,
)
_HYPOTHETICAL: Final[re.Pattern[str]] = re.compile(
    r"(會怎樣|會不會|如果|假如|萬一|危不危險|安全嗎|有風險嗎|"
    r"應該點|可以點|能不能點|要不要點|點了會)",
)
_DEICTIC_LINK: Final[re.Pattern[str]] = re.compile(
    r"(這則|這封|這條|那則|簡訊|訊息|短信).{0,16}(url|網址|連結|鏈接)",
    re.IGNORECASE,
)
_CLAUSE_CONNECTOR: Final[re.Pattern[str]] = re.compile(
    r"\s*再\s*(幫我)?\s*|\s*然後\s*|\s*順便\s*|\s*並且\s*|[，,、]",
)


@dataclass
class RouteResult:
    confidence: Confidence
    task_type: str
    task_state: str
    todos: list[PlanStep]
    reason_codes: list[str] = field(default_factory=list)


def split_clauses(user_text: str) -> list[str]:
    """依連接詞切子句；單句則回傳一元素列表。"""
    t = strip_planner_system_prefix((user_text or "").strip())
    if not t:
        return []
    normalized = _CLAUSE_CONNECTOR.sub("|||", t)
    parts = [p.strip() for p in normalized.split("|||") if p.strip()]
    return parts if parts else [t]


def _strip_search_prefix(clause: str) -> str:
    t = _SEARCH_PREFIX.sub("", (clause or "").strip())
    t = _GOOGLE_SEARCH.sub("", t).strip()
    return t


def _normalize_location(loc: str) -> str:
    t = (loc or "").strip()
    for suffix in _TEMPORAL_SUFFIX:
        if t.endswith(suffix) and len(t) > len(suffix):
            t = t[: -len(suffix)]
    return t.strip()


def _extract_weather_location(clause: str) -> str:
    t = _strip_search_prefix(clause)
    for pat in _WEATHER_LOCATION_PATTERNS:
        m = pat.search(t)
        if m:
            loc = _normalize_location((m.group(1) or "").strip())
            if loc and loc not in ("今天", "明天", "後天", "后天", "查", "搜"):
                return loc
    return ""


def _clause_has_weather(clause: str) -> bool:
    return bool(_WEATHER_OBJECT.search(_strip_search_prefix(clause)))


def _clause_has_fetch_intent(clause: str) -> bool:
    return bool(_FETCH_INTENT.search(clause)) and bool(
        re.search(r"https?://", clause, re.IGNORECASE)
    )


def _clause_open_url(clause: str) -> str:
    """子句層級：是否要求開啟 URL（排除假設問句）。"""
    if _HYPOTHETICAL.search(clause):
        return ""
    if _DEICTIC_LINK.search(clause) and not re.search(r"https?://", clause, re.IGNORECASE):
        return ""
    if not re.search(r"https?://", clause, re.IGNORECASE):
        if not _OPEN_VERB.search(clause):
            return ""
    url = resolve_open_url_from_user_text(clause)
    if not url:
        return ""
    if _OPEN_VERB.search(clause) or re.search(r"https?://", clause, re.IGNORECASE):
        return url
    return ""


def _build_search_query(clause: str) -> str:
    t = _strip_search_prefix(clause)
    t = re.sub(r"https?://[^\s<>\"']+", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\s+", " ", t).strip(" ，,、")
    return t


def _clause_wants_search(clause: str) -> bool:
    t = (clause or "").strip()
    if _clause_has_weather(t):
        return False
    if _GOOGLE_SEARCH.search(t):
        return True
    if _SEARCH_PREFIX.search(t):
        return True
    if t.startswith("查") and "是什麼" not in t and "什麼是" not in t:
        if not _clause_has_weather(t):
            return True
    return False


def route_single_clause(clause: str) -> tuple[PlanStep | None, list[str]]:
    """單一子句 → skill；無法判定時回傳 (None, reasons)。"""
    c = (clause or "").strip()
    if not c:
        return None, ["empty_clause"]

    if _clause_has_weather(c):
        loc = _extract_weather_location(c)
        if loc:
            return PlanStep(skill="weather", args={"location": loc}), ["object_weather"]
        return None, ["weather_no_location"]

    if _clause_has_fetch_intent(c):
        url = resolve_open_url_from_user_text(c)
        if url:
            return PlanStep(skill="fetch_url", args={"url": url}), ["fetch_url_intent"]

    open_url = _clause_open_url(c)
    if open_url and not _clause_has_fetch_intent(c):
        return PlanStep(
            skill="open_url_readonly",
            args={"url": open_url},
        ), ["open_explicit_url"]

    if _clause_wants_search(c):
        if _DEICTIC.search(c):
            return None, ["deictic_needs_context"]
        q = _build_search_query(c)
        if q:
            return PlanStep(skill="search_web", args={"query": q}), ["explicit_search"]
        return None, ["search_no_query"]

    return None, ["unclassified_clause"]


def route_user_text(user_text: str) -> RouteResult:
    """
    複合句語意路由主入口。

    confidence=high：可覆寫 Planner LLM todos。
    confidence=low/none：交回原流程。
    """
    text = strip_planner_system_prefix((user_text or "").strip())
    if not text:
        return RouteResult(confidence="none", task_type="unknown", task_state="new", todos=[])

    # L0：假設／風險詢問（不真的開瀏覽器、不排工具）
    if _HYPOTHETICAL.search(text) and (
        _DEICTIC_LINK.search(text) or _OPEN_VERB.search(text)
    ):
        return RouteResult(
            confidence="high",
            task_type="direct_response",
            task_state="answering",
            todos=[],
            reason_codes=["hypothetical_risk_question"],
        )

    # L0：審查意圖 + 有 URL／正文
    if _REVIEW_INTENT.search(text):
        artifact = text
        m = re.search(r"https?://[^\s<>\"']+", text, re.IGNORECASE)
        if m:
            artifact = m.group(0).rstrip(".,;)")
        return RouteResult(
            confidence="high",
            task_type="check",
            task_state="running",
            todos=[
                PlanStep(
                    skill="call_dai",
                    args={"artifact": artifact, "user_text": text},
                )
            ],
            reason_codes=["review_intent_with_payload"],
        )

    clauses = split_clauses(text)
    if not clauses:
        return RouteResult(confidence="none", task_type="unknown", task_state="new", todos=[])

    steps: list[PlanStep] = []
    reasons: list[str] = []
    for clause in clauses:
        step, clause_reasons = route_single_clause(clause)
        if step is None:
            return RouteResult(
                confidence="low",
                task_type="action",
                task_state="new",
                todos=[],
                reason_codes=reasons + clause_reasons,
            )
        steps.append(step)
        reasons.extend(clause_reasons)

    if not steps:
        return RouteResult(confidence="none", task_type="unknown", task_state="new", todos=[])

    return RouteResult(
        confidence="high",
        task_type="action",
        task_state="running",
        todos=steps,
        reason_codes=reasons,
    )


def apply_semantic_router(
    *,
    user_text: str,
    todos: list[PlanStep],
    task_type: str,
    task_state: str,
    ingress_requires_dai: bool = False,
    ingress_detected_task_type: str = "",
) -> tuple[list[PlanStep], str, str, bool]:
    """
    Planner validate 之後：高信心語意路由覆寫 todos，並跳過 open/search guards。

    ingress_requires_dai 時不覆寫（交給 Ingress／validate 的送審流程）。
    回傳第四個值 applied=True 表示已採用路由結果。
    """
    if ingress_requires_dai:
        return todos, task_type, task_state, False

    routed = route_user_text(user_text)
    if routed.confidence != "high":
        return todos, task_type, task_state, False

    if routed.task_type == "direct_response":
        return routed.todos, routed.task_type, routed.task_state, True

    if routed.task_type == "check":
        return routed.todos, routed.task_type, routed.task_state, True

    if (
        routed.task_type == "action"
        and (ingress_detected_task_type or "").lower() != "check"
    ):
        return routed.todos, routed.task_type, routed.task_state, True

    return todos, task_type, task_state, False
