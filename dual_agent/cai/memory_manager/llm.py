"""
Memory Manager LLM：語意分析（intent／relation／value／mode）。

程式端仍負責輕量正規化（normalize_relation、normalize_person_name）與把關
（confidence、append 雙重檢查、pending），見 normalize_memory_decision 與 manager。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.cai.context_layer import RELATION_ALIASES, normalize_relation
from dual_agent.cai.memory_manager.schemas import MemoryDecision
from dual_agent.config import OLLAMA_BASE_URL, cai_memory_model
from dual_agent.llm_json import coerce_llm_text, invoke_and_parse_json

_MEMORY_SYSTEM_PROMPT = """你只輸出單一 JSON 物件，不要 markdown。鍵名必須如下。

intent（必填，其一）：
- remember_set：使用者陳述某關係的姓名，且為該關係的第一筆或覆寫（例：我媽媽叫 mei、哥哥叫 zack、我哥叫 zack）
- remember_append：在已有關係上追加姓名（例：還有 David、另有 Jay）
- forget：要求忘記某關係或成員
- recall：詢問已記住的關係／姓名／人數（例：媽媽叫什麼、專題組員有誰）
- clarify：無法判斷關係或姓名，需追問
- none：一般聊天、天氣、送審簡訊、搜尋、問助理身份等，與記憶無關

規則：
1. 已知多種關係時，新句中的關係詞（哥哥、媽媽、專題組員等）決定 relation，不得套用到其他已記關係。
2. 口語稱呼正規化後寫入 relation（我哥/老媽→哥哥/媽媽）；原文保留在 raw_relation。
3. value 僅為人名；口語清洗後寫入 value，原文保留在 raw_value。
4. remember_set 時 mode=set；remember_append 時 mode=append；其餘 intent 時 mode 可為空字串。
5. 若使用者要追加但句中未指明關係且無法從語意唯一推斷，intent=clarify，勿猜測。
6. recall 且已知 facts 中該關係無姓名時，answer 可為空（由程式組句）；有資料則簡短回答。
7. forget 時 relation 盡量填目標關係；若只說「忘記這兩個人」且 facts 僅一種關係，填該關係。
8. 若存在待確認記憶、使用者只回「是的/不是」，intent=none（由程式處理 affirm/deny）。
9. confidence 0.0–1.0：確定記憶操作 ≥0.8；模糊則降低；完全非記憶 intent=none 且 confidence 可低。
10. reason 簡短說明判斷依據（除錯用，不直接給使用者）。

JSON 輸出必含鍵（單一物件、不要 markdown）：
intent, raw_relation, relation, raw_value, value, mode, confidence, answer, reason。

常見同義詞參考（非限制）：{alias_hint}。"""


def _coerce_memory_decision(obj: dict[str, Any]) -> MemoryDecision | None:
    if not isinstance(obj, dict):
        return None
    intent = coerce_llm_text(obj.get("intent")).lower()
    valid_intents = {
        "remember_set",
        "remember_append",
        "forget",
        "recall",
        "clarify",
        "none",
    }
    if intent not in valid_intents:
        return None
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    mode = coerce_llm_text(obj.get("mode")).lower()
    if mode not in ("set", "append", ""):
        mode = "append" if intent == "remember_append" else "set" if intent == "remember_set" else ""
    return MemoryDecision(
        intent=intent,  # type: ignore[arg-type]
        raw_relation=coerce_llm_text(obj.get("raw_relation")),
        relation=coerce_llm_text(obj.get("relation")),
        raw_value=coerce_llm_text(obj.get("raw_value")),
        value=coerce_llm_text(obj.get("value")),
        mode=mode,  # type: ignore[arg-type]
        confidence=conf,
        answer=coerce_llm_text(obj.get("answer")),
        reason=coerce_llm_text(obj.get("reason")),
    )


def normalize_memory_decision(decision: MemoryDecision) -> MemoryDecision:
    """LLM 輸出後的輕量正規化（同義詞、姓名清洗）。"""
    from dual_agent.cai.memory_direct import normalize_person_name

    rel = normalize_relation(decision.relation or decision.raw_relation)
    raw_val = (decision.value or decision.raw_value or "").strip()
    val = normalize_person_name(raw_val) or raw_val
    mode = decision.mode
    if decision.intent == "remember_set":
        mode = "set"
    elif decision.intent == "remember_append":
        mode = "append"
    return decision.model_copy(
        update={
            "relation": rel,
            "value": val,
            "mode": mode,
        }
    )


def invoke_memory_turn_llm(
    user_text: str,
    known_facts_json: str,
    context_pack: str | None = None,
    *,
    model: str | None = None,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.0,
) -> MemoryDecision | None:
    text = (user_text or "").strip()
    if not text or len(text) > 500:
        return None

    mem_model = model or cai_memory_model()
    alias_hint = "、".join(sorted(set(RELATION_ALIASES.keys())))
    ctx_snippet = ""
    if context_pack:
        ctx_snippet = (context_pack or "")[:800]

    # 勿將 JSON／使用者原文直接 f-string 進模板：大括號會觸發 format spec 錯誤。
    human_template = (
        "已知 user_facts（JSON）：\n{known_facts_json}\n\n"
        "使用者訊息：\n{user_text}"
    )
    if ctx_snippet:
        human_template = (
            "對話脈絡摘要（勿與待確認混淆）：\n{context_pack}\n\n" + human_template
        )
    prompt_vars: dict[str, str] = {
        "alias_hint": alias_hint,
        "known_facts_json": known_facts_json,
        "user_text": text,
        "context_pack": ctx_snippet,
    }

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _MEMORY_SYSTEM_PROMPT),
            ("human", human_template),
        ]
    )
    llm = ChatOllama(model=mem_model, base_url=base_url, temperature=temperature)
    chain = prompt | llm | StrOutputParser()

    def _invoke() -> str:
        return chain.invoke(prompt_vars)

    def _retry_invoke() -> str:
        retry_prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "只輸出合法 JSON 物件，鍵名 intent, relation, value, mode, confidence, answer, reason。"
                    " intent 必為 remember_set|remember_append|forget|recall|clarify|none 之一。",
                ),
                ("human", human_template),
            ]
        )
        retry_chain = retry_prompt | llm | StrOutputParser()
        return retry_chain.invoke(prompt_vars)

    try:
        obj = invoke_and_parse_json(_invoke, retry_invoke=_retry_invoke)
    except (ValueError, KeyError, TypeError):
        return None
    decision = _coerce_memory_decision(obj)
    if decision is None:
        return None
    return normalize_memory_decision(decision)


def serialize_known_facts(user_facts: dict[str, Any] | None) -> str:
    from dual_agent.cai.context_layer import normalize_user_facts

    uf = normalize_user_facts(user_facts)
    return json.dumps(uf.get("relations") or {}, ensure_ascii=False)
