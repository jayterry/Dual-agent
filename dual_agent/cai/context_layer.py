"""
Memory / Context Layer（對齊設計圖）：

- 長期記憶：user_profile（App 註冊基本資料）+ rolling_summary（對話壓縮摘要）
- Recent Context Buffer：最近 N 輪使用者／助理對話
- Task Snapshot：上一輪 task_type / task_state（送審後含 review_phase、last_risk_score 等）

Context Packer：pack_context() → 供 Planner / Replan / DAI 共用的脈絡字串。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.config import context_buffer_max_rounds


@dataclass
class ConversationTurn:
    """單輪寫入緩衝：對話 + 任務／計畫／執行摘要（供日後 Replan 回答「剛做了什麼」等）。"""

    user: str
    assistant: str
    task_type: str = ""
    task_state: str = ""
    plan_summary: str = ""
    result_summary: str = ""


@dataclass
class SessionMemory:
    """單一工作階段記憶（程式內；未接 RAG / DB）。"""

    rolling_summary: str = ""
    recent_buffer: list[ConversationTurn] = field(default_factory=list)
    task_snapshot: dict[str, Any] = field(default_factory=dict)
    user_profile: dict[str, Any] = field(default_factory=dict)
    user_facts: dict[str, Any] = field(default_factory=dict)


# 人際關係同義詞 → 正規化稱呼（非允許清單；未列者保留原文）
RELATION_ALIASES: dict[str, str] = {
    "母親": "媽媽",
    "媽": "媽媽",
    "媽媽": "媽媽",
    "父親": "爸爸",
    "爸": "爸爸",
    "爸爸": "爸爸",
}


def default_user_facts() -> dict[str, Any]:
    return {"profile": {}, "relations": {}}


def normalize_relation(relation: str) -> str:
    """將同義詞正規化；不在 RELATION_ALIASES 則保留原文（如「弟弟」）。"""
    r = (relation or "").strip()
    if not r:
        return r
    return RELATION_ALIASES.get(r, r)


def _coerce_relation_names(value: Any) -> list[str]:
    """單一姓名或 list 皆轉成去重後的姓名列表。"""
    if isinstance(value, list):
        names = [str(x).strip() for x in value if str(x).strip()]
    else:
        s = str(value or "").strip()
        names = [s] if s else []
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        key = n.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(n)
    return out


def _merge_name_lists(existing: list[str], new_names: list[str]) -> list[str]:
    merged = list(existing)
    seen = {n.casefold() for n in merged}
    for n in new_names:
        k = n.casefold()
        if k in seen:
            continue
        seen.add(k)
        merged.append(n)
    return merged


def normalize_user_facts(raw: dict[str, Any] | None) -> dict[str, Any]:
    """統一為 {profile, relations}；relations 值為 list[str]；相容舊版單一字串。"""
    if not raw or not isinstance(raw, dict):
        return default_user_facts()
    if "profile" in raw or "relations" in raw:
        relations: dict[str, list[str]] = {}
        for k, v in dict(raw.get("relations") or {}).items():
            rel = normalize_relation(str(k))
            names = _coerce_relation_names(v)
            if not rel or not names:
                continue
            relations[rel] = _merge_name_lists(relations.get(rel, []), names)
        return {
            "profile": dict(raw.get("profile") or {}),
            "relations": relations,
        }
    legacy_map = {
        "mother_name": "媽媽",
        "father_name": "爸爸",
        "spouse_name": "配偶",
        "child_name": "子女",
    }
    relations: dict[str, list[str]] = {}
    profile: dict[str, str] = {}
    for key, val in raw.items():
        names = _coerce_relation_names(val)
        if not names:
            continue
        if key in legacy_map:
            rel = normalize_relation(legacy_map[key])
            relations[rel] = _merge_name_lists(relations.get(rel, []), names)
        elif key in ("user_name", "assistant_name"):
            profile[key] = names[0]
        else:
            rel = normalize_relation(key)
            relations[rel] = _merge_name_lists(relations.get(rel, []), names)
    return {"profile": profile, "relations": relations}


def get_relation_names(user_facts: dict[str, Any] | None, relation: str) -> list[str]:
    uf = normalize_user_facts(user_facts)
    rel = normalize_relation(relation)
    return list((uf.get("relations") or {}).get(rel) or [])


def format_relation_names(names: list[str]) -> str:
    """繁中列舉：A、B 和 C。"""
    picked = [str(n).strip() for n in names if str(n).strip()]
    if not picked:
        return ""
    if len(picked) == 1:
        return picked[0]
    if len(picked) == 2:
        return f"{picked[0]} 和 {picked[1]}"
    return "、".join(picked[:-1]) + f" 和 {picked[-1]}"


def _compact_summary_value(value: Any, *, max_chars: int = 120) -> Any:
    if isinstance(value, str):
        s = " ".join(value.strip().split())
        if len(s) <= max_chars:
            return s
        return s[: max_chars - 1] + "…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    try:
        s = json.dumps(value, ensure_ascii=False)
    except TypeError:
        s = str(value)
    s = " ".join(s.strip().split())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _summary_args_for_plan_step(skill: str, args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    summarized: dict[str, Any] = {}
    for key, value in args.items():
        if key == "context_pack":
            summarized[key] = "（已省略）"
            continue
        if skill == "call_dai" and key == "artifact":
            summarized[key] = _compact_summary_value(value, max_chars=160)
            continue
        summarized[key] = _compact_summary_value(value)
    return summarized


def build_plan_summary(plan: list[Any] | None, *, max_steps: int = 12, max_json_chars: int = 320) -> str:
    """將本輪 plan（PlanStep 列表）壓成可進 Context 的一小段文字。"""
    if not plan:
        return "（本輪顯示之計畫步驟為空）"
    lines: list[str] = []
    for i, st in enumerate(plan[:max_steps], 1):
        sk = getattr(st, "skill", "?")
        args = _summary_args_for_plan_step(sk, getattr(st, "args", None) or {})
        try:
            aj = json.dumps(args, ensure_ascii=False)
        except TypeError:
            aj = str(args)
        if len(aj) > max_json_chars:
            aj = aj[: max_json_chars - 3] + "..."
        lines.append(f"{i}. {sk} {aj}")
    if len(plan) > max_steps:
        lines.append(f"…（另有 {len(plan) - max_steps} 步省略）")
    return "\n".join(lines)


def _truncate(s: str, max_chars: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 20] + "\n…（已截斷）"


def _norm_artifact_key(text: str) -> str:
    return "".join(str(text or "").split()).strip().lower()


_ASSISTANT_NAME = "CAI"

_USER_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"我(?:是|叫)(?:你(?:的)?)?(?:主人|老闆|使用者)?\s*([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\u00b7.\-]{0,24})",
        re.IGNORECASE,
    ),
    re.compile(
        r"display_name=([A-Za-z\u4e00-\u9fff][\w\u4e00-\u9fff\u00b7.\-]{0,24})",
        re.IGNORECASE,
    ),
)


def extract_user_display_name_from_pack(context_pack: str | None) -> str | None:
    pack = (context_pack or "").strip()
    if not pack:
        return None
    skip = frozenset({"誰", "什麼", "你的", "助手", "助理", "主人"})
    found: list[tuple[int, str]] = []
    for pat in _USER_NAME_PATTERNS:
        for m in pat.finditer(pack):
            name = (m.group(1) or "").strip()
            if name and name not in skip:
                found.append((m.start(), name))
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    return found[-1][1]


extract_user_display_name = extract_user_display_name_from_pack


def merge_user_profile(session: SessionMemory, profile: dict[str, Any] | None) -> None:
    """合併 App 傳入的 user_profile（display_name、user_id）。"""
    if not profile or not isinstance(profile, dict):
        return
    merged = dict(session.user_profile or {})
    uid = str(profile.get("user_id") or profile.get("userId") or "").strip()
    name = str(profile.get("display_name") or profile.get("displayName") or "").strip()
    if uid:
        merged["user_id"] = uid
    if name:
        merged["display_name"] = name
    merged["assistant_name"] = _ASSISTANT_NAME
    session.user_profile = merged


def display_name_from_profile(user_profile: dict[str, Any] | None) -> str | None:
    if not user_profile:
        return None
    name = str(user_profile.get("display_name") or "").strip()
    return name or None


def merge_profile_fact(session: SessionMemory, key: str, value: str) -> None:
    k = (key or "").strip()
    v = (value or "").strip()
    if not k or not v:
        return
    uf = normalize_user_facts(session.user_facts)
    uf["profile"][k] = v
    session.user_facts = uf


def merge_relation_fact(
    session: SessionMemory,
    relation: str,
    value: str,
    *,
    append: bool = False,
) -> None:
    """寫入已確認的人際關係：relations[稱呼] = [姓名, ...]。"""
    rel = normalize_relation(relation)
    val = (value or "").strip()
    if not rel or not val:
        return
    uf = normalize_user_facts(session.user_facts)
    if append:
        uf["relations"][rel] = _merge_name_lists(uf["relations"].get(rel, []), [val])
    else:
        uf["relations"][rel] = _merge_name_lists([], [val])
    session.user_facts = uf


def append_relation_value(
    session: SessionMemory,
    relation: str,
    value: str,
) -> None:
    """追加一名至既有關係（不覆寫其他人）。"""
    merge_relation_fact(session, relation, value, append=True)


def clear_relation_in_user_facts(
    user_facts: dict[str, Any] | None,
    relation: str,
) -> dict[str, Any]:
    """清空指定關係的姓名列表（自 relations 移除該鍵）。"""
    uf = normalize_user_facts(user_facts)
    rel = normalize_relation(relation)
    if rel:
        uf["relations"].pop(rel, None)
    return uf


def clear_relation_fact(session: SessionMemory, relation: str) -> None:
    """Session 層級清空已確認的關係事實。"""
    session.user_facts = clear_relation_in_user_facts(session.user_facts, relation)


def remove_confirmed_fact_from_rolling_summary(session: SessionMemory, relation: str) -> None:
    """移除 rolling_summary 中該關係的「使用者告知：{rel}為 …」行。"""
    rel = normalize_relation(relation)
    if not rel:
        return
    prefix = f"使用者告知：{rel}為"
    existing = (session.rolling_summary or "").strip()
    if not existing:
        return
    kept = [ln for ln in existing.split("\n") if not ln.strip().startswith(prefix)]
    session.rolling_summary = "\n".join(kept).strip()


def append_confirmed_fact_to_rolling_summary(
    session: SessionMemory,
    relation: str,
    value: str | list[str] | None = None,
) -> None:
    """確認後立即寫入長期摘要，下一輪 pack_context 即可引用。"""
    rel = normalize_relation(relation)
    uf = normalize_user_facts(session.user_facts)
    names = _coerce_relation_names(value) if value is not None else list(uf["relations"].get(rel) or [])
    if not names:
        return
    label = format_relation_names(names)
    line = f"使用者告知：{rel}為 {label}。"
    existing = (session.rolling_summary or "").strip()
    if line in existing:
        return
    session.rolling_summary = f"{existing}\n{line}".strip() if existing else line


def format_user_facts_block(
    user_facts: dict[str, Any] | None,
    *,
    relations_filter: list[str] | None = None,
    header: str | None = None,
) -> str:
    uf = normalize_user_facts(user_facts)
    profile = uf.get("profile") or {}
    relations: dict[str, list[str]] = dict(uf.get("relations") or {})
    if relations_filter:
        allowed = {normalize_relation(r) for r in relations_filter if str(r).strip()}
        relations = {
            rel: names
            for rel, names in relations.items()
            if normalize_relation(rel) in allowed
        }
    if not profile and not relations:
        return ""
    title = header or "── 使用者告知的事實（本輪相關；回答關係／姓名問題請直接引用）"
    lines = [title, "使用者告知的事實："]
    for rel, names in sorted(relations.items(), key=lambda x: x[0]):
        lines.append(f"- {rel}：{format_relation_names(names)}")
    for key, val in sorted(profile.items(), key=lambda x: x[0]):
        lines.append(f"- {key}：{val}")
    return "\n".join(lines)


def format_episodic_memory_block(session: SessionMemory, *, max_summary_chars: int = 8000) -> str:
    """【長期記憶】僅含 App 基本資料與對話摘要（不含 user_facts 關係事實）。"""
    lines: list[str] = ["【長期記憶】"]
    prof = session.user_profile or {}
    if prof:
        lines.append("── 使用者基本資料（App 註冊；「我是誰」答此稱呼，「你是誰」答 CAI 助理）")
        uid = str(prof.get("user_id") or "").strip()
        name = str(prof.get("display_name") or "").strip()
        if uid:
            lines.append(f"user_id={uid}")
        if name:
            lines.append(f"display_name={name}")
        lines.append(f"assistant_name={prof.get('assistant_name') or _ASSISTANT_NAME}")
    rs = (session.rolling_summary or "").strip()
    if rs:
        lines.append("── 對話長期摘要")
        lines.append(_truncate(rs, max_summary_chars))
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def format_long_term_memory_block(session: SessionMemory, *, max_summary_chars: int = 8000) -> str:
    """向後相容：episodic + session 內全部 user_facts（測試／舊呼叫端）。"""
    parts: list[str] = []
    episodic = format_episodic_memory_block(session, max_summary_chars=max_summary_chars)
    if episodic:
        parts.append(episodic)
    facts_block = format_user_facts_block(session.user_facts)
    if facts_block:
        parts.append(facts_block)
    return "\n\n".join(parts) if parts else ""


def is_same_artifact_as_snapshot(
    task_snapshot: dict[str, Any] | None,
    artifact_text: str,
) -> bool:
    """本輪附带的正文是否與 snapshot 中已審的 artifact_key 相同。"""
    snap = dict(task_snapshot or {})
    stored_key = str(snap.get("artifact_key") or "").strip()
    if not stored_key:
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return False
    new_key = _norm_artifact_key(new_art)
    if new_key == stored_key:
        return True
    if len(stored_key) >= 4 and (stored_key in new_key or new_key in stored_key):
        return True
    return False


def should_block_repeat_call_dai(
    task_snapshot: dict[str, Any] | None,
    *,
    artifact_text: str = "",
    user_text: str = "",
) -> bool:
    """
    是否應阻止本輪再排 call_dai（底線，非路由模式）：
    已完成審查且本輪無新正文，或正文與已審相同，且使用者未要求再審。
    """
    snap = dict(task_snapshot or {})
    if str(snap.get("review_phase") or "").strip() != "review_completed":
        return False
    if re.search(r"再審|重新審|重審|審查一次", (user_text or "").strip()):
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return True
    return is_same_artifact_as_snapshot(snap, new_art)


def is_follow_up_on_completed_review(
    user_text: str,
    *,
    task_snapshot: dict[str, Any] | None = None,
    review_work_state: dict[str, Any] | None = None,
    artifact_text: str = "",
) -> bool:
    """向後相容：已審完成且本輪未附新正文（或與已審相同）。"""
    del user_text
    snap = dict(task_snapshot or {})
    if not snap and review_work_state:
        snap = {
            "review_phase": review_work_state.get("phase"),
            "artifact_key": review_work_state.get("artifact_key"),
        }
    if str(snap.get("review_phase") or "").strip() != "review_completed":
        return False
    new_art = (artifact_text or "").strip()
    if not new_art:
        return True
    return is_same_artifact_as_snapshot(snap, new_art)


def format_work_state_summary(task_snapshot: dict[str, Any] | None) -> str:
    """將 task_snapshot 轉成 Planner 可讀的繁中摘要（JSON 仍保留於 pack_context）。"""
    snap = dict(task_snapshot or {})
    if not snap:
        return ""
    phase = str(snap.get("review_phase") or "").strip() or "（未送審）"
    lines = [f"階段：{phase}"]
    score = snap.get("last_risk_score")
    if isinstance(score, (int, float)):
        lines.append(f"上次風險分數：{int(score)}/100")
    summ = str(snap.get("last_safety_summary") or "").strip()
    if summ:
        lines.append(f"上次摘要：{summ[:200]}")
    ex = str(snap.get("artifact_excerpt") or "").strip()
    if ex:
        lines.append(f"已審正文摘要：{ex[:120]}…")
    src = str(snap.get("message_source") or "").strip()
    if src and src.lower() not in ("unknown", "（無）"):
        lines.append(f"來源：{src}")
    if phase == "review_completed":
        lines.append(
            "若本輪 user prompt 僅詢問分數／身份／來源，通常 todos=[]、勿 call_dai；"
            "若本輪附全新可疑正文或使用者要求再審，可 call_dai。"
        )
    return "\n".join(lines)


def pack_episodic_context(session: SessionMemory, *, max_chars_per_turn: int = 6000) -> str:
    """對話緩衝、長期摘要、任務狀態（不含 user_facts 關係事實）。"""
    parts: list[str] = []
    lt = format_episodic_memory_block(session, max_summary_chars=max_chars_per_turn * 2)
    if lt:
        parts.append(lt)
    if session.recent_buffer:
        chunks: list[str] = []
        for i, t in enumerate(session.recent_buffer, 1):
            u = _truncate(t.user, max_chars_per_turn)
            a = _truncate(t.assistant, max_chars_per_turn)
            meta_lines: list[str] = [
                f"task_type={_truncate((t.task_type or '（無）'), 80)}",
                f"task_state={_truncate((t.task_state or '（無）'), 80)}",
            ]
            if (t.plan_summary or "").strip():
                meta_lines.append(f"計畫摘要：\n{_truncate(t.plan_summary, max_chars_per_turn)}")
            if (t.result_summary or "").strip():
                meta_lines.append(f"執行結果摘要：\n{_truncate(t.result_summary, max_chars_per_turn)}")
            meta = "\n".join(meta_lines)
            chunks.append(
                f"（緩衝第 {i} 輪）\n{meta}\n使用者：{u}\n助理：{a}"
            )
        parts.append("【最近對話緩衝】\n" + "\n\n".join(chunks))
    ts = session.task_snapshot or {}
    if ts:
        summary = format_work_state_summary(ts)
        block = "【上一輪任務狀態】\n"
        if summary:
            block += summary + "\n\n"
        block += json.dumps(ts, ensure_ascii=False)
        parts.append(block)
    if not parts:
        return "（尚無累積脈絡：可視為對話開頭或尚未寫回記憶。）"
    return "\n\n".join(parts)


def pack_factual_context(
    user_facts: dict[str, Any] | None,
    *,
    relations_filter: list[str] | None = None,
) -> str:
    """本輪相關的 user_facts 子集（由 retrieve 決定是否注入）。"""
    block = format_user_facts_block(
        user_facts,
        relations_filter=relations_filter,
        header="【本輪相關事實】",
    )
    return block


def build_context_pack(
    session: SessionMemory,
    *,
    retrieval: Any,
    user_facts: dict[str, Any] | None = None,
    max_chars_per_turn: int = 6000,
) -> str:
    """依 MemoryRetrievalResult 組裝 Context Pack（episodic + 可選 factual slice）。"""
    parts: list[str] = [pack_episodic_context(session, max_chars_per_turn=max_chars_per_turn)]
    if getattr(retrieval, "inject_facts", False):
        uf = normalize_user_facts(user_facts if user_facts is not None else session.user_facts)
        factual = pack_factual_context(
            uf,
            relations_filter=list(getattr(retrieval, "inject_relations", None) or []) or None,
        )
        if factual:
            parts.append(factual)
    return "\n\n".join(p for p in parts if p)


def build_context_pack_for_turn(
    session: SessionMemory,
    user_text: str,
    *,
    user_facts: dict[str, Any] | None = None,
    pending_memory_confirm: dict[str, Any] | None = None,
    memory_intent: str | None = None,
    max_chars_per_turn: int = 6000,
) -> str:
    """Retrieve 後組裝本輪 Context Pack。"""
    from dual_agent.cai.memory_retrieval import retrieve_memory_for_turn

    uf = normalize_user_facts(user_facts if user_facts is not None else session.user_facts)
    retrieval = retrieve_memory_for_turn(
        user_text,
        user_facts=uf,
        pending_memory_confirm=pending_memory_confirm,
        memory_intent=memory_intent,
    )
    return build_context_pack(
        session,
        retrieval=retrieval,
        user_facts=uf,
        max_chars_per_turn=max_chars_per_turn,
    )


def pack_context(session: SessionMemory, *, max_chars_per_turn: int = 6000) -> str:
    """組成 Context Pack（預設僅 episodic；不含 user_facts 關係事實）。"""
    return pack_episodic_context(session, max_chars_per_turn=max_chars_per_turn)


def merge_into_rolling_summary(
    existing_summary: str,
    turn: ConversationTurn,
    *,
    model: str,
    base_url: str,
    temperature: float = 0.2,
) -> str:
    """將移出緩衝的一輪對話併入長期摘要（單次 LLM 呼叫）。"""
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """你是對話記憶壓縮助手。請把「既有長期摘要」與「即將移出緩衝的一輪對話」合併成一段新的長期摘要（繁體中文）。
保留：使用者目標、約定、偏好、未完成事項、重要名詞與結論；若有「計畫摘要／執行結果摘要」，請保留其中與事實、工具行為相關的要點（例如曾搜尋什麼、成功與否）。
省略：寒暄、重複語句、與後續對話無關的細節。
只輸出摘要本文，不要標題、markdown、JSON。""",
            ),
            (
                "human",
                """【既有長期摘要】
{existing}

【本輪摘要（移出緩衝）】
task_type={task_type}
task_state={task_state}
計畫摘要：
{plan_summary}
執行結果摘要：
{result_summary}

使用者：{user}
助理：{assistant}""",
            ),
        ]
    )
    raw = (prompt | llm | StrOutputParser()).invoke(
        {
            "existing": (existing_summary or "").strip() or "（尚無）",
            "task_type": (turn.task_type or "").strip() or "（無）",
            "task_state": (turn.task_state or "").strip() or "（無）",
            "plan_summary": (turn.plan_summary or "").strip() or "（無）",
            "result_summary": (turn.result_summary or "").strip() or "（無）",
            "user": turn.user.strip(),
            "assistant": turn.assistant.strip(),
        }
    )
    return (raw or "").strip()


def _fallback_merge(existing_summary: str, turn: ConversationTurn) -> str:
    meta = "\n".join(
        [
            f"task_type={turn.task_type or '（無）'}",
            f"task_state={turn.task_state or '（無）'}",
            f"計畫：{(turn.plan_summary or '').strip() or '（無）'}",
            f"執行：{(turn.result_summary or '').strip() or '（無）'}",
        ]
    )
    block = f"{meta}\n使用者：{turn.user.strip()}\n助理：{turn.assistant.strip()}"
    if not (existing_summary or "").strip():
        return block
    return f"{existing_summary.strip()}\n\n---\n{block}"


def record_turn(
    session: SessionMemory,
    *,
    user: str,
    assistant: str,
    task_type: str,
    task_state: str,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    plan_summary: str = "",
    result_summary: str = "",
) -> None:
    """
    本輪結束後寫回：append 緩衝、更新 task_snapshot；若超過 CONTEXT_BUFFER_MAX_ROUNDS
    則反覆將最舊一輪壓入 rolling_summary。
    """
    cap = context_buffer_max_rounds()
    session.recent_buffer.append(
        ConversationTurn(
            user=user.strip(),
            assistant=(assistant or "").strip(),
            task_type=(task_type or "").strip(),
            task_state=(task_state or "").strip(),
            plan_summary=(plan_summary or "").strip(),
            result_summary=(result_summary or "").strip(),
        )
    )
    session.task_snapshot = {
        "task_type": (task_type or "").strip(),
        "task_state": (task_state or "").strip(),
    }
    while len(session.recent_buffer) > cap:
        oldest = session.recent_buffer.pop(0)
        try:
            session.rolling_summary = merge_into_rolling_summary(
                session.rolling_summary,
                oldest,
                model=model,
                base_url=base_url,
                temperature=temperature,
            )
        except Exception:
            session.rolling_summary = _fallback_merge(session.rolling_summary, oldest)


def record_turn_after_review(
    session: SessionMemory,
    *,
    user: str,
    assistant: str,
    task_type: str,
    task_state: str,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    plan_summary: str = "",
    result_summary: str = "",
    artifact: str = "",
    message_source: str = "",
    input_origin: str = "",
    dai: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """送審結束：與一般聊天相同 record_turn，並擴充 task_snapshot 供追問。"""
    record_turn(
        session,
        user=user,
        assistant=assistant,
        task_type=task_type,
        task_state=task_state,
        model=model,
        base_url=base_url,
        temperature=temperature,
        plan_summary=plan_summary,
        result_summary=result_summary,
    )
    art = (artifact or "").strip()
    dai_payload = dict(dai or {})
    snap: dict[str, Any] = {
        "task_type": (task_type or "check").strip(),
        "task_state": (task_state or "completed").strip(),
        "review_phase": "review_completed",
        "has_dai_result": True,
        "message_source": (message_source or "").strip() or "unknown",
        "input_origin": (input_origin or "").strip() or "unknown",
        "artifact_key": _norm_artifact_key(art),
        "artifact_excerpt": _truncate(art, 400),
    }
    score = dai_payload.get("risk_score")
    if isinstance(score, (int, float)):
        snap["last_risk_score"] = int(score)
    summ = str(dai_payload.get("safety_summary") or "").strip()
    if summ:
        snap["last_safety_summary"] = _truncate(summ, 500)
    action = str(dai_payload.get("recommended_cai_action") or "").strip()
    if action:
        snap["last_recommended_action"] = action
    session.task_snapshot = snap
    return snap


# 向後相容別名
record_review_outcome = record_turn_after_review
