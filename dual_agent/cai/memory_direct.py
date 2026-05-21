"""
個人關係事實的確認與寫入。

user_facts：{"profile": {}, "relations": {"媽媽": ["Yuri"], "專題組員": ["ruby", "David"]}}
RELATION_ALIASES 僅用於同義詞正規化，不作允許清單。
"""

from __future__ import annotations

from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.cai.context_layer import (
    RELATION_ALIASES,
    clear_relation_in_user_facts,
    format_relation_names,
    get_relation_names,
    normalize_relation,
    normalize_user_facts,
)
from dual_agent.cai.schemas import PlanExecuteOutcome
from dual_agent.llm_json import coerce_llm_bool, coerce_llm_text, invoke_and_parse_json
from dual_agent.skill_types import SkillContext

_AFFIRMATIVE_REPLIES: frozenset[str] = frozenset(
    {
        "是",
        "是的",
        "对",
        "對",
        "沒錯",
        "没错",
        "好",
        "好的",
        "yes",
        "y",
        "ok",
        "恩",
        "嗯",
    }
)

_DENY_REPLIES: frozenset[str] = frozenset(
    {
        "不是",
        "不对",
        "不對",
        "错",
        "錯",
        "否",
        "no",
        "n",
    }
)

_ADDITIVE_PREFIXES: tuple[str, ...] = ("還有", "还有", "另有", "加上", "以及", "再加")

_FORGET_TOKENS: tuple[str, ...] = (
    "忘記",
    "忘掉",
    "刪除記憶",
    "不要記",
    "別記",
    "清除記憶",
    "換組員",
    "換了組員",
    "重新記",
    "換人",
    "不記了",
)

_FORGET_TARGET_TOKENS: tuple[str, ...] = (
    "這兩個",
    "这两个",
    "他們",
    "她们",
    "这些人",
    "這些人",
    "全部",
    "都",
)

_RELATION_HINT_TOKENS: tuple[str, ...] = (
    "組員",
    "成員",
    "家人",
    "親戚",
    "同事",
    "同學",
    "媽媽",
    "妈妈",
    "爸爸",
    "母親",
    "父亲",
    "父親",
    "弟弟",
    "妹妹",
    "專題組員",
)

_NAME_FILLER_PREFIXES: tuple[str, ...] = ("一個人", "一个人", "另一位", "還有", "还有")

_INVALID_NAME_SUBSTRINGS: tuple[str, ...] = ("一個人", "一个人", "組員", "專題", "還有", "还有")

_RECALL_QUERY_TOKENS: tuple[str, ...] = (
    "誰",
    "谁",
    "有誰",
    "有谁",
    "現在有",
    "目前有",
    "叫什麼",
    "叫什么",
    "有哪些",
)


def is_affirmative_reply(user_text: str) -> bool:
    """待確認時的確定性肯定（不依賴 LLM）。"""
    raw = (user_text or "").strip()
    if not raw:
        return False
    compact = "".join(raw.split())
    if compact.lower() in _AFFIRMATIVE_REPLIES:
        return True
    return raw.lower() in _AFFIRMATIVE_REPLIES


def is_deny_reply(user_text: str) -> bool:
    raw = (user_text or "").strip()
    if not raw:
        return False
    compact = "".join(raw.split())
    if compact.lower() in _DENY_REPLIES:
        return True
    return raw.lower() in _DENY_REPLIES


def _strip_name_punctuation(text: str) -> str:
    t = (text or "").strip()
    while t and t[0] in "，,。.!！?？ ":
        t = t[1:].strip()
    while t and t[-1] in "，,。.!！?？ ":
        t = t[:-1].strip()
    return t


def normalize_person_name(fragment: str) -> str | None:
    """
    從口語片段抽出單一人名（確定性清洗，不用 regex）。
    例：「一個人，就Ossa」→ Ossa；「叫做ossa」→ ossa。
    """
    t = _strip_name_punctuation(fragment)
    if not t:
        return None
    for _ in range(8):
        changed = False
        for prefix in _NAME_FILLER_PREFIXES:
            if t.startswith(prefix):
                t = _strip_name_punctuation(t[len(prefix) :])
                changed = True
        if not changed:
            break
    for guide in ("叫做", "就是"):
        if guide in t:
            t = _strip_name_punctuation(t.split(guide)[-1])
    if "就" in t:
        tail = _strip_name_punctuation(t.split("就")[-1])
        if tail and len(tail) < len(t):
            t = tail
    if t.startswith("叫") and len(t) > 1:
        t = _strip_name_punctuation(t[1:])
    t = _strip_name_punctuation(t)
    if not t or len(t) > 32:
        return None
    if t in ("就", "是", "有", "人", "一個", "一个"):
        return None
    for bad in _INVALID_NAME_SUBSTRINGS:
        if bad in t:
            return None
    return t


def looks_like_forget_memory_turn(user_text: str) -> bool:
    """使用者要求忘記已記住的人際關係。"""
    t = (user_text or "").strip()
    if not t or len(t) > 120:
        return False
    if not any(tok in t for tok in _FORGET_TOKENS):
        return False
    if any(tok in t for tok in _RELATION_HINT_TOKENS):
        return True
    if any(tok in t for tok in _FORGET_TARGET_TOKENS):
        return True
    if "換" in t and "組員" in t:
        return True
    return False


def infer_relation_from_query_text(user_text: str) -> str | None:
    """從問句推斷關係稱呼（無需已有 relations）。"""
    text = (user_text or "").strip()
    if not text:
        return None
    if "專題組員" in text:
        return "專題組員"
    hits: list[str] = []
    for tok in _RELATION_HINT_TOKENS:
        if tok in text:
            hits.append(normalize_relation(tok))
    hits = list(dict.fromkeys(hits))
    if len(hits) == 1:
        return hits[0]
    if "組員" in text:
        return "專題組員"
    return None


def infer_relation_for_forget(
    user_facts: dict[str, Any] | None,
    user_text: str,
) -> str | None:
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    text = (user_text or "").strip()
    if relations:
        rel = _find_relation_in_query(text, relations)
        if rel:
            return rel
        if len(relations) == 1:
            return next(iter(relations))
    return infer_relation_from_query_text(text)


def looks_like_relation_recall_query(user_text: str) -> bool:
    t = (user_text or "").strip()
    return bool(t) and any(tok in t for tok in _RECALL_QUERY_TOKENS)


def try_recall_empty_relation(user_text: str, user_facts: dict[str, Any] | None) -> str | None:
    """關係查詢但尚未記錄任何姓名。"""
    if not looks_like_relation_recall_query(user_text):
        return None
    text = (user_text or "").strip()
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    rel = _find_relation_in_query(text, relations) if relations else None
    if not rel:
        rel = infer_relation_from_query_text(text)
    if not rel:
        return None
    names = list((relations.get(rel) or []))
    if names:
        return None
    return f"目前尚未記錄您的{rel}。若要記住新組員，請直接告訴我名字。"


def looks_like_memory_clarification_turn(user_text: str) -> bool:
    """
    澄清／枚舉已記住的人際關係（如「我有兩個組員」「組員有誰」），應走記憶而非 DAI。
    """
    t = (user_text or "").strip()
    if looks_like_forget_memory_turn(t):
        return False
    if not t or len(t) > 80:
        return False
    relation_tokens = ("組員", "成員", "家人", "親戚", "同事", "同學")
    clarify_tokens = (
        "兩個",
        "两个",
        "幾個",
        "几个",
        "多少",
        "誰",
        "谁",
        "什麼",
        "什么",
        "哪些",
        "有誰",
        "有谁",
        "叫什麼",
        "叫什么",
    )
    if not any(tok in t for tok in relation_tokens):
        return False
    return any(tok in t for tok in clarify_tokens)


def build_confirm_question(
    relation: str,
    value: str,
    *,
    existing_names: list[str] | None = None,
    mode: str = "set",
) -> str:
    rel = normalize_relation(relation)
    val = (value or "").strip()
    if mode == "append" and existing_names:
        have = format_relation_names(existing_names)
        return f"要一併記住您的{rel}叫 {val} 嗎？目前已有 {have}。"
    return f"您是說您的{rel}叫 {val} 嗎？"


def try_parse_additive_name(user_text: str) -> str | None:
    """「還有 David」→ 僅回傳姓名（不含 relation）。"""
    t = (user_text or "").strip()
    if not t:
        return None
    for prefix in _ADDITIVE_PREFIXES:
        if t.startswith(prefix):
            rest = t[len(prefix) :].strip().strip("，,。.!！?？")
            if rest:
                return normalize_person_name(rest)
    if "叫做" in t or t.startswith("叫"):
        name = normalize_person_name(t)
        if name:
            return name
    return None


def infer_relation_for_additive(
    user_facts: dict[str, Any] | None,
    user_text: str,
) -> str | None:
    """追加時若僅有一種關係已記住，或句中含該稱呼，則推斷 relation。"""
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if not relations:
        return None
    t = (user_text or "").strip()
    hits: list[str] = []
    for rel in relations:
        if rel and rel in t:
            hits.append(rel)
    if len(hits) == 1:
        return hits[0]
    if len(relations) == 1:
        return next(iter(relations))
    return None


def parse_relation_memory_statement(
    user_text: str,
    *,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    user_facts: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    從使用者陳述抽取待確認的關係事實。
    命中回傳：{"fact_type": "relation", "relation": "媽媽", "value": "Yuri", "mode": "set"|"append"}
    """
    text = (user_text or "").strip()
    if not text or len(text) > 500:
        return None

    additive_name = try_parse_additive_name(text)
    if additive_name:
        rel = infer_relation_for_additive(user_facts, text)
        if rel:
            return {
                "fact_type": "relation",
                "relation": rel,
                "value": additive_name,
                "mode": "append",
            }

    alias_hint = "、".join(sorted(set(RELATION_ALIASES.keys())))
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你只輸出單一 JSON 物件，不要 markdown。"
                "若使用者只是在陳述某個人際關係的姓名／稱呼（例如：我媽媽叫 Yuri、我弟弟是 Jay），"
                "has_fact=true，並輸出 relation（原文稱呼）與 value（姓名）。"
                "若使用者說「還有某人」要追加到同一關係，mode=append。"
                "relation 可為任意中文稱呼，不限於特定清單。"
                f"常見同義詞參考（僅供理解，非限制）：{alias_hint}。"
                "若是一般聊天、問句、送審、搜尋、問助理身份，has_fact=false。",
            ),
            ("human", "使用者訊息：{user_text}"),
        ]
    )
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    chain = prompt | llm | StrOutputParser()

    def _invoke() -> str:
        return chain.invoke({"user_text": text})

    try:
        obj = invoke_and_parse_json(_invoke)
    except ValueError:
        return None

    if not coerce_llm_bool(obj.get("has_fact")):
        return None
    relation_raw = coerce_llm_text(obj.get("relation"))
    value_raw = coerce_llm_text(obj.get("value"))
    if not relation_raw or not value_raw:
        return None
    value = normalize_person_name(value_raw) or _strip_name_punctuation(value_raw)
    if not value:
        return None
    if len(value) > 64:
        value = value[:64]
    relation = normalize_relation(relation_raw)
    mode = coerce_llm_text(obj.get("mode")).lower() or "set"
    if mode not in ("set", "append"):
        mode = "append" if try_parse_additive_name(text) else "set"
    return {
        "fact_type": "relation",
        "relation": relation,
        "value": value,
        "mode": mode,
    }


def _classify_memory_reply_llm(
    user_text: str,
    *,
    pending_question: str,
    relation: str,
    value: str,
    model: str,
    base_url: str,
    temperature: float,
) -> str:
    """待確認狀態下判斷使用者回覆。回傳：affirm | deny | other"""
    if is_affirmative_reply(user_text):
        return "affirm"
    if is_deny_reply(user_text):
        return "deny"

    text = (user_text or "").strip()
    if not text:
        return "other"

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你只輸出單一 JSON 物件。鍵名 intent，值必須為 affirm、deny 或 other。"
                "affirm：使用者同意先前確認（是的、對、沒錯、yes 等）。"
                "deny：使用者否定或更正（不是、不對、錯了等）。"
                "other：新話題、補充說明、無關內容。",
            ),
            (
                "human",
                "待確認：{relation}={value}\n"
                "助理先前問題：{pending_question}\n"
                "使用者本輪回覆：{user_text}",
            ),
        ]
    )
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    chain = prompt | llm | StrOutputParser()

    def _invoke() -> str:
        return chain.invoke(
            {
                "user_text": text,
                "pending_question": pending_question,
                "relation": relation,
                "value": value,
            }
        )

    try:
        obj = invoke_and_parse_json(_invoke)
    except ValueError:
        return "other"
    intent = coerce_llm_text(obj.get("intent")).lower()
    if intent in ("affirm", "deny", "other"):
        return intent
    return "other"


def _relation_keys_for_lookup(relations: dict[str, list[str]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for canonical in relations:
        lookup[canonical] = canonical
        for alias, norm in RELATION_ALIASES.items():
            if norm == canonical:
                lookup[alias] = canonical
    return lookup


def _find_relation_in_query(user_text: str, relations: dict[str, list[str]]) -> str | None:
    if not relations:
        return None
    text = (user_text or "").strip()
    if not text:
        return None
    lookup = _relation_keys_for_lookup(relations)
    hits: list[tuple[int, str]] = []
    for token, canonical in lookup.items():
        if token and token in text:
            hits.append((text.index(token), canonical))
    if not hits:
        return None
    hits.sort(key=lambda x: x[0])
    return hits[-1][1]


def _find_relation_by_value(user_text: str, relations: dict[str, list[str]]) -> tuple[str, str] | None:
    text = (user_text or "").strip()
    if not text:
        return None
    for rel, names in relations.items():
        for name in names:
            n = (name or "").strip()
            if n and n in text:
                return rel, n
    return None


def _format_recall_answer(relation: str, names: list[str]) -> str:
    rel = normalize_relation(relation)
    label = format_relation_names(names)
    if len(names) <= 1:
        return f"依先前記錄，您的{rel}是 {label}。"
    return f"依先前記錄，您的{rel}有 {label}。"


def try_recall_from_user_facts(user_text: str, user_facts: dict[str, Any] | None) -> str | None:
    """
    依 relations 確定性回想（單人、多人、人數澄清、反向誰是誰）。
    """
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if not relations:
        return None
    text = (user_text or "").strip()
    if not text:
        return None

    if looks_like_forget_memory_turn(text):
        return None

    count_tokens = ("兩個", "两个", "幾個", "几个", "多少", "幾位", "几位")
    if any(tok in text for tok in count_tokens):
        rel = _find_relation_in_query(text, relations)
        if not rel and len(relations) == 1:
            rel = next(iter(relations))
        if rel:
            names = relations.get(rel) or []
            n = len(names)
            if n == 0:
                return None
            label = format_relation_names(names)
            if any(tok in text for tok in ("兩個", "两个")) and n == 2:
                return f"依先前記錄，您的{rel}有兩位：{label}。"
            return f"依先前記錄，您的{rel}共有 {n} 位：{label}。"

    by_val = _find_relation_by_value(text, relations)
    if by_val and any(k in text for k in ("誰", "是誰", "什麼人", "哪位")):
        rel, name = by_val
        return f"依先前記錄，{name} 是您的{rel}。"

    rel = _find_relation_in_query(text, relations)
    if rel and any(k in text for k in ("什麼", "叫", "名字", "誰", "嗎", "哪些", "有誰", "有谁")):
        names = relations.get(rel) or []
        if names:
            return _format_recall_answer(rel, names)

    if looks_like_memory_clarification_turn(text):
        if len(relations) == 1:
            rel = next(iter(relations))
            names = relations[rel]
            if names:
                return _format_recall_answer(rel, names)

    return None


def _recall_fact_llm(
    user_text: str,
    *,
    user_facts: dict[str, Any],
    model: str,
    base_url: str,
    temperature: float,
) -> str | None:
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if not relations:
        return None
    text = (user_text or "").strip()
    if not text:
        return None

    rel_lines = [
        f"{rel}={format_relation_names(names)}" for rel, names in relations.items()
    ]
    facts_json = "；".join(rel_lines)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你只輸出單一 JSON 物件。"
                "若使用者是在詢問已記住的人際關係或某人身份（含同義詞如母親/媽媽），"
                "wants_recall=true 且 relation 為已知關係鍵。"
                "若問「X 是誰」且 X 為已知姓名，wants_recall=true、recall_mode=by_value、value=X。"
                "否則 wants_recall=false。",
            ),
            (
                "human",
                "已知關係：{facts_json}\n使用者訊息：{user_text}",
            ),
        ]
    )
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    chain = prompt | llm | StrOutputParser()

    def _invoke() -> str:
        return chain.invoke({"user_text": text, "facts_json": facts_json})

    try:
        obj = invoke_and_parse_json(_invoke)
    except ValueError:
        return None
    if not coerce_llm_bool(obj.get("wants_recall")):
        return None
    mode = coerce_llm_text(obj.get("recall_mode")).lower()
    if mode == "by_value":
        val = coerce_llm_text(obj.get("value"))
        found = _find_relation_by_value(val or text, relations)
        if found:
            rel, name = found
            return f"依先前記錄，{name} 是您的{rel}。"
        return None
    rel_raw = coerce_llm_text(obj.get("relation"))
    rel = normalize_relation(rel_raw)
    names = relations.get(rel) or []
    if names:
        return _format_recall_answer(rel, names)
    return None


def _apply_confirmed_relation(
    user_facts: dict[str, Any] | None,
    relation: str,
    value: str,
    *,
    mode: str = "set",
) -> dict[str, Any]:
    from dual_agent.cai.context_layer import _merge_name_lists

    uf = normalize_user_facts(user_facts)
    rel = normalize_relation(relation)
    val = normalize_person_name(value) or _strip_name_punctuation(value)
    if not rel or not val:
        return uf
    if mode == "append":
        uf["relations"][rel] = _merge_name_lists(uf["relations"].get(rel, []), [val])
    else:
        uf["relations"][rel] = _merge_name_lists([], [val])
    return uf


def _outcome(answer: str, *, task_state: str) -> PlanExecuteOutcome:
    return PlanExecuteOutcome(
        plan=[],
        results=[],
        answer=answer,
        task_type="direct_response",
        task_state=task_state,
    )


def _clear_pending_memory(ctx: SkillContext) -> None:
    ctx.policy_state.pop("pending_memory_confirm", None)
    ctx.policy_state.pop("pending_task", None)
    ctx.policy_state.pop("pending_user_question", None)


def try_handle_memory_turn(
    user_text: str,
    *,
    ctx: SkillContext,
    user_facts: dict[str, Any] | None,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    parse_fn: Any = None,
    classify_fn: Any = None,
    recall_fn: Any = None,
) -> PlanExecuteOutcome | None:
    """
    記憶確認短路：命中則回 PlanExecuteOutcome，否則 None（交給 Planner）。
    """
    uf = normalize_user_facts(user_facts)
    if not isinstance(ctx.policy_state.get("user_facts"), dict):
        ctx.policy_state["user_facts"] = normalize_user_facts(uf)
    else:
        uf = normalize_user_facts(ctx.policy_state.get("user_facts"))

    _parse = parse_fn or parse_relation_memory_statement
    _classify = classify_fn or _classify_memory_reply_llm
    _recall_llm = recall_fn or _recall_fact_llm

    pending = ctx.policy_state.get("pending_memory_confirm")
    if isinstance(pending, dict) and pending.get("value"):
        relation = str(pending.get("relation") or "").strip()
        value = str(pending["value"])
        mode = str(pending.get("mode") or "set").strip().lower()
        if not relation and pending.get("fact_key"):
            relation = normalize_relation(str(pending["fact_key"]))
        if relation:
            question = str(
                pending.get("question")
                or build_confirm_question(relation, value, mode=mode)
            )
            if is_affirmative_reply(user_text):
                intent = "affirm"
            elif is_deny_reply(user_text):
                intent = "deny"
            else:
                intent = _classify(
                    user_text,
                    pending_question=question,
                    relation=relation,
                    value=value,
                    model=model,
                    base_url=base_url,
                    temperature=temperature,
                )
            if intent == "affirm":
                ctx.policy_state["user_facts"] = _apply_confirmed_relation(
                    ctx.policy_state.get("user_facts"),
                    relation,
                    value,
                    mode=mode,
                )
                _clear_pending_memory(ctx)
                ctx.policy_state.pop("pending_review", None)
                rel = normalize_relation(relation)
                names = get_relation_names(ctx.policy_state.get("user_facts"), rel)
                label = format_relation_names(names)
                if mode == "append" and len(names) > 1:
                    return _outcome(
                        f"好的，已記住。您的{rel}有 {label}。",
                        task_state="completed",
                    )
                return _outcome(
                    f"好的，已記住您的{rel}是 {label}。",
                    task_state="completed",
                )
            if intent == "deny":
                _clear_pending_memory(ctx)
                return _outcome(
                    "了解，那我先不記這筆。請再告訴我正確的稱呼或關係。",
                    task_state="waiting_input",
                )
            return None

    if looks_like_forget_memory_turn(user_text):
        rel = infer_relation_for_forget(uf, user_text)
        relations_now: dict[str, list[str]] = dict(uf.get("relations") or {})
        if not rel and relations_now:
            if len(relations_now) == 1:
                rel = next(iter(relations_now))
            else:
                return _outcome(
                    "請告訴我要忘記哪一種關係（例如專題組員、媽媽）。",
                    task_state="waiting_input",
                )
        if rel:
            ctx.policy_state["user_facts"] = clear_relation_in_user_facts(
                ctx.policy_state.get("user_facts"),
                rel,
            )
            _clear_pending_memory(ctx)
            ctx.policy_state.pop("pending_review", None)
            rel_label = normalize_relation(rel)
            return _outcome(
                f"好的，已忘記您先前記錄的{rel_label}。若要記住新的成員，請直接告訴我名字。",
                task_state="completed",
            )
        return _outcome(
            "目前沒有已記錄的人際關係可忘記。",
            task_state="completed",
        )

    empty_recall = try_recall_empty_relation(user_text, uf)
    if empty_recall:
        ctx.policy_state.pop("pending_review", None)
        return _outcome(empty_recall, task_state="completed")

    recalled = try_recall_from_user_facts(user_text, uf)
    if recalled:
        ctx.policy_state.pop("pending_review", None)
        return _outcome(recalled, task_state="completed")

    if looks_like_memory_clarification_turn(user_text):
        if relations := dict(uf.get("relations") or {}):
            if len(relations) == 1:
                rel = next(iter(relations))
                names = relations[rel]
                if names:
                    ctx.policy_state.pop("pending_review", None)
                    return _outcome(_format_recall_answer(rel, names), task_state="completed")

    additive_name_hint = try_parse_additive_name(user_text)
    if additive_name_hint:
        additive_parsed = _parse(
            user_text,
            model=model,
            base_url=base_url,
            temperature=temperature,
            user_facts=uf,
        )
        if not additive_parsed or additive_parsed.get("fact_type") != "relation":
            rel_hint = infer_relation_for_additive(uf, user_text)
            if rel_hint:
                additive_parsed = {
                    "fact_type": "relation",
                    "relation": rel_hint,
                    "value": additive_name_hint,
                    "mode": "append",
                }
        if additive_parsed and additive_parsed.get("fact_type") == "relation":
            relation = str(additive_parsed.get("relation") or "")
            value = str(additive_parsed.get("value") or "")
            mode = str(additive_parsed.get("mode") or "append").strip().lower()
            if mode not in ("set", "append"):
                mode = "append"
            if relation and value:
                existing = get_relation_names(uf, relation) if mode == "append" else []
                question = build_confirm_question(
                    relation,
                    value,
                    existing_names=existing,
                    mode=mode,
                )
                ctx.policy_state["pending_memory_confirm"] = {
                    "fact_type": "relation",
                    "relation": normalize_relation(relation),
                    "value": value,
                    "mode": mode,
                    "question": question,
                }
                ctx.policy_state["pending_task"] = {
                    "type": "ask_user",
                    "question": question,
                    "rationale": "確認使用者告知的關係事實後再寫入記憶",
                    "expected_task": "direct_response",
                }
                ctx.policy_state["pending_user_question"] = question
                return _outcome(question, task_state="waiting_input")

    recalled_llm = _recall_llm(
        user_text,
        user_facts=uf,
        model=model,
        base_url=base_url,
        temperature=temperature,
    )
    if recalled_llm:
        ctx.policy_state.pop("pending_review", None)
        return _outcome(recalled_llm, task_state="completed")

    parsed = _parse(
        user_text,
        model=model,
        base_url=base_url,
        temperature=temperature,
        user_facts=uf,
    )
    if not parsed or parsed.get("fact_type") != "relation":
        return None

    relation = str(parsed.get("relation") or "")
    value = str(parsed.get("value") or "")
    mode = str(parsed.get("mode") or "set").strip().lower()
    if mode not in ("set", "append"):
        mode = "set"
    if not relation or not value:
        return None

    existing = get_relation_names(uf, relation) if mode == "append" else []
    question = build_confirm_question(
        relation,
        value,
        existing_names=existing,
        mode=mode,
    )
    ctx.policy_state["pending_memory_confirm"] = {
        "fact_type": "relation",
        "relation": normalize_relation(relation),
        "value": value,
        "mode": mode,
        "question": question,
    }
    ctx.policy_state["pending_task"] = {
        "type": "ask_user",
        "question": question,
        "rationale": "確認使用者告知的關係事實後再寫入記憶",
        "expected_task": "direct_response",
    }
    ctx.policy_state["pending_user_question"] = question
    return _outcome(question, task_state="waiting_input")
