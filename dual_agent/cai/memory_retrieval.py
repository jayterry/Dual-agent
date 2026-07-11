"""
記憶檢索層：決定本輪 Context Pack 是否注入 user_facts（Store → Retrieve → Apply）。

不相關輪次（寒暄、評論）不注入事實區塊，避免 Replan 主動洩漏未詢問的關係／姓名。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dual_agent.cai.context_layer import normalize_relation, normalize_user_facts
from dual_agent.cai.memory_direct import (
    looks_like_forget_memory_turn,
    looks_like_memory_clarification_turn,
)

_RECALL_QUERY_TOKENS: tuple[str, ...] = (
    "誰",
    "谁",
    "什麼",
    "什么",
    "叫什麼",
    "叫什么",
    "名字",
    "哪些",
    "有誰",
    "有谁",
    "記得",
    "记得",
    "是誰",
    "是谁",
    "幾個",
    "几个",
    "多少",
    "兩個",
    "两个",
    "幾位",
    "几位",
    "嗎",
    "吗",
)

_MEMORY_WRITE_INTENTS: frozenset[str] = frozenset(
    {"remember_set", "remember_append", "forget", "recall"}
)

_INVENTORY_TOKENS: tuple[str, ...] = (
    "記憶裡",
    "记忆里",
    "記得什麼",
    "记得什么",
    "記住什麼",
    "记住什么",
    "記住甚麼",
    "記得甚麼",
    "記了些什麼",
    "記了什麼",
    "有什麼記憶",
    "有甚麼記憶",
    "你記得",
    "你記住",
)

_CONTRADICTION_TOKENS: tuple[str, ...] = (
    "怎麼會說",
    "怎么会说",
    "不是剛",
    "不是刚",
    "剛才",
    "刚才",
    "為什麼說",
    "为什么说",
    "沒記住",
    "没记住",
)


@dataclass
class MemoryRetrievalResult:
    inject_facts: bool = False
    inject_relations: list[str] = field(default_factory=list)
    reason: str = ""


def looks_like_memory_inventory_turn(user_text: str) -> bool:
    """詢問「記憶裡有什麼／你記得什麼」等元問題（非單一 relation 回想）。"""
    t = (user_text or "").strip()
    if not t or looks_like_forget_memory_turn(t):
        return False
    if any(tok in t for tok in _INVENTORY_TOKENS):
        return True
    if "記憶" in t and any(tok in t for tok in ("什麼", "什么", "甚麼", "哪些")):
        return True
    return False


def looks_like_memory_contradiction_turn(user_text: str) -> bool:
    """追問先前回答與記憶狀態矛盾（如「你怎麼會說沒記住」）。"""
    t = (user_text or "").strip()
    if not t:
        return False
    return any(tok in t for tok in _CONTRADICTION_TOKENS)


def looks_like_explicit_recall_turn(user_text: str) -> bool:
    """本輪是否像在明確詢問已記住的人物／關係（非寒暄、非評論）。"""
    t = (user_text or "").strip()
    if not t or looks_like_forget_memory_turn(t):
        return False
    if looks_like_memory_inventory_turn(t):
        return True
    if looks_like_memory_contradiction_turn(t):
        return True
    if looks_like_memory_clarification_turn(t):
        return True
    return any(tok in t for tok in _RECALL_QUERY_TOKENS)


def _relations_for_turn(
    user_text: str,
    user_facts: dict[str, Any] | None,
    *,
    intent: str,
) -> list[str]:
    uf = normalize_user_facts(user_facts)
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if not relations:
        return []
    text = (user_text or "").strip()
    matched: list[str] = []
    for rel in relations:
        if rel in text or normalize_relation(rel) in text:
            matched.append(rel)
    if matched:
        return matched
    if intent == "recall" and looks_like_explicit_recall_turn(text):
        if len(relations) == 1:
            return [next(iter(relations))]
        return list(relations.keys())
    if intent in ("remember_set", "remember_append", "forget"):
        return list(relations.keys())
    return []


def retrieve_memory_for_turn(
    user_text: str,
    *,
    user_facts: dict[str, Any] | None = None,
    pending_memory_confirm: dict[str, Any] | None = None,
    memory_intent: str | None = None,
) -> MemoryRetrievalResult:
    """
    決定本輪是否將 user_facts 注入 Context Pack。

    儲存層仍保留全部 facts；此函式只控制「展示／注入」。
    """
    if isinstance(pending_memory_confirm, dict) and pending_memory_confirm.get("value"):
        rel = str(pending_memory_confirm.get("relation") or "").strip()
        rels = [rel] if rel else []
        return MemoryRetrievalResult(True, rels, "pending_memory_confirm")

    intent = (memory_intent or "").strip().lower()
    if intent in _MEMORY_WRITE_INTENTS:
        rels = _relations_for_turn(user_text, user_facts, intent=intent)
        return MemoryRetrievalResult(True, rels, f"memory_intent={intent}")

    if looks_like_memory_inventory_turn(user_text) or looks_like_memory_contradiction_turn(
        user_text
    ):
        uf = normalize_user_facts(user_facts)
        rels = list((uf.get("relations") or {}).keys())
        return MemoryRetrievalResult(True, rels, "memory_meta")

    if looks_like_explicit_recall_turn(user_text):
        rels = _relations_for_turn(user_text, user_facts, intent="recall")
        return MemoryRetrievalResult(True, rels, "explicit_recall")

    return MemoryRetrievalResult(False, [], "not_relevant")


def should_allow_memory_recall(
    user_text: str,
    *,
    memory_intent: str | None = None,
) -> bool:
    """Memory Manager 是否允許走 recall（含 LLM 誤判時的程式底線）。"""
    intent = (memory_intent or "").strip().lower()
    if intent == "recall":
        return (
            looks_like_explicit_recall_turn(user_text)
            or looks_like_memory_clarification_turn(user_text)
            or looks_like_memory_inventory_turn(user_text)
            or looks_like_memory_contradiction_turn(user_text)
        )
    return False
