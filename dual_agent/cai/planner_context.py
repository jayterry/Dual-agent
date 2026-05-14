"""
Planner 與 Context Pack：可測的搜尋意圖與 search_web query 補全（不依賴 LLM）。

與 planner_llm 內提示詞對齊；當模型仍錯排 todos 時，invoke_planner 會呼叫此處補正。
"""

from __future__ import annotations

import re
from typing import Final

from dual_agent.cai.schemas import PlanStep

# 接續上一輪（僅應出現在給 Planner 的 payload 開頭，不可進 search_web query）
_CONTINUATION_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^【接續上一輪】[^\n]*\n+",
    re.MULTILINE,
)


def strip_planner_system_prefix(text: str) -> str:
    """移除 _planner_payload 注入的接續區塊，還原本輪實質輸入（供意圖／搜尋補全）。"""
    t = (text or "").strip()
    t = _CONTINUATION_HEAD.sub("", t, count=1)
    return t.strip()


def sanitize_search_web_query_string(query: str) -> str:
    """移除誤抄入 query 的系統接續字樣與多餘換行。"""
    q = (query or "").strip()
    q = _CONTINUATION_HEAD.sub("", q, count=1)
    q = re.sub(r"【接續上一輪】", "", q)
    q = re.sub(r"先前問題：", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def collapse_redundant_search_web(todos: list[PlanStep]) -> list[PlanStep]:
    """
    合併連續多筆 search_web（常見於模型重複排程）：優先採用不含接續字樣的 query，否則取最後一筆清理後結果。
    """
    if not todos:
        return todos
    out: list[PlanStep] = []
    i = 0
    while i < len(todos):
        st = todos[i]
        if st.skill != "search_web":
            out.append(st)
            i += 1
            continue
        j = i
        queries: list[str] = []
        while j < len(todos) and todos[j].skill == "search_web":
            q = sanitize_search_web_query_string(str((todos[j].args or {}).get("query") or ""))
            if q:
                queries.append(q)
            j += 1
        if not queries:
            i = j
            continue
        pick = queries[-1]
        for q in reversed(queries):
            if "接續" in q or "先前問題" in q:
                continue
            pick = q
            break
        pick = sanitize_search_web_query_string(pick)
        if pick:
            out.append(PlanStep(skill="search_web", args={"query": pick}))
        i = j
    return out


def normalize_search_query_dedupe_key(q: str) -> str:
    """用於判斷是否為同一語意搜尋（簡繁／空白正規化）。"""
    t = (q or "").strip().lower()
    t = t.replace("天气", "天氣")
    t = t.replace("航线", "路線")
    t = re.sub(r"\s+", " ", t)
    return t


def dedupe_search_web_in_plan(todos: list[PlanStep]) -> list[PlanStep]:
    """整份 plan：正規化後相同的 search_web 只保留第一筆（避免連排三次同義查詢）。"""
    seen: set[str] = set()
    out: list[PlanStep] = []
    for st in todos:
        if st.skill != "search_web":
            out.append(st)
            continue
        q = sanitize_search_web_query_string(str((st.args or {}).get("query") or ""))
        if not q:
            continue
        key = normalize_search_query_dedupe_key(q)
        if key in seen:
            continue
        seen.add(key)
        out.append(PlanStep(skill="search_web", args={"query": q}))
    return out
_SEARCH_TRIGGER: Final[str] = (
    r"(搜尋|幫我搜|上網查|上網找|上網搜|網路上查|幫我查|查一下|"
    r"查詢我|查詢這|查詢那|查詢「|查詢『|查詢\s*「|查詢\s*『)"
)

_DEICTIC: Final[str] = r"(我喜歡的|喜歡的遊戲|剛剛那個|前面那則|那一款|那個遊戲|那款遊戲)"

# 從 Context Pack 可抽出的常見實體（可再擴充）
_KNOWN_GAME_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("英雄聯盟", "英雄聯盟"),
    ("英雄联盟", "英雄聯盟"),
    ("League of Legends", "英雄聯盟"),
    ("LOL", "英雄聯盟"),
    ("lol", "英雄聯盟"),
    ("Apex Legends", "Apex Legends"),
    ("APEX", "Apex Legends"),
    ("apex", "Apex Legends"),
)


def explicit_web_search_requested(user_text: str) -> bool:
    """本輪是否明確要求上網搜尋／查詢（優先於純記憶回答）。"""
    t = strip_planner_system_prefix((user_text or "").strip())
    if not t:
        return False
    if re.search(r"(?i)google", t):
        return True
    if re.search(_SEARCH_TRIGGER, t):
        return True
    # 「查詢…」作為動詞開頭（排除「是什麼」純問句標題誤觸）
    if t.startswith("查詢") and "是什麼" not in t and "什麼是" not in t:
        return True
    return False


def _has_deictic(user_text: str) -> bool:
    return bool(re.search(_DEICTIC, (user_text or "").strip()))


def extract_entity_hints_from_context(context_pack: str) -> list[str]:
    """從 Context Pack 抽出已知實體（canonical 名稱，去重保序）。"""
    ctx = context_pack or ""
    out: list[str] = []
    seen: set[str] = set()
    for needle, canonical in _KNOWN_GAME_MARKERS:
        if needle in ctx and canonical not in seen:
            out.append(canonical)
            seen.add(canonical)
    return out


def _suffix_from_user(user_text: str) -> str:
    """使用者句中除觸發詞外、可併入 query 的片語（如 最近更新）。"""
    t = (user_text or "").strip()
    # 去掉常見觸發前綴
    t = re.sub(r"^(搜尋|幫我搜|查詢|幫我查|上網查|上網找|上網搜|網路上查|查一下)\s*", "", t)
    t = re.sub(r"(?i)^google\s*", "", t)
    t = t.strip()
    # 保留像「最近更新、版本、新聞」等尾巴
    return t


def build_search_web_query(user_text: str, context_pack: str | None) -> str:
    """
    產生 search_web 的 query：觸發詞補全 + Context 指涉解析。
    若指涉詞存在但 Context 無可補實體，回傳空字串（呼叫端應改 ask_user）。
    """
    raw = strip_planner_system_prefix((user_text or "").strip())
    ctx = (context_pack or "").strip()
    hints = extract_entity_hints_from_context(ctx)

    if _has_deictic(raw):
        if not hints:
            return ""
        anchor = hints[0]
        tail = _suffix_from_user(raw)
        # 去掉仍含指涉的冗餘，保留具體補語
        tail = re.sub(_DEICTIC, "", tail)
        tail = re.sub(r"^[的遊戲\s，、]+", "", tail).strip()
        parts = [anchor]
        if tail and tail not in anchor and anchor not in tail:
            parts.append(tail)
        return " ".join(parts).strip()

    tail = _suffix_from_user(raw)
    if tail:
        return tail
    return raw


def should_force_search_web_todos(user_text: str, todos_skill_names: list[str]) -> bool:
    """LLM 漏排 search_web 時是否需強制補上。"""
    if not explicit_web_search_requested(user_text):
        return False
    if not todos_skill_names:
        return True
    return todos_skill_names[0] != "search_web"


def apply_explicit_search_guard(
    *,
    user_text: str,
    context_pack: str | None,
    todos: list,
    task_type: str,
    task_state: str,
) -> tuple[list, str, str]:
    """
    若本輪明確網搜：確保 todos[0] 為 search_web，並調整 task_type / task_state。
    todos 為 PlanStep 列表（會原地替換 skill/args 或整表重建）。
    """
    from dual_agent.cai.schemas import PlanStep

    ut = strip_planner_system_prefix((user_text or "").strip())
    names = [getattr(s, "skill", "") for s in todos]
    if not explicit_web_search_requested(ut):
        return todos, task_type, task_state

    if not should_force_search_web_todos(ut, names):
        # 已是 search_web 為首：僅補強 query 若空或仍含指涉
        if todos and todos[0].skill == "search_web":
            q = str((todos[0].args or {}).get("query") or "").strip()
            if not q or _has_deictic(q):
                built = build_search_web_query(ut, context_pack)
                if built:
                    todos[0] = PlanStep(skill="search_web", args={"query": built})
                elif not q:
                    todos[0] = PlanStep(
                        skill="ask_user",
                        args={
                            "question": "無法從既有對話推斷要搜尋的主題，請寫出要查的遊戲或關鍵字名稱。",
                            "rationale": "明確網搜但 Context 無法補全指涉詞",
                        },
                    )
        tt = task_type
        ts = task_state
        if todos and getattr(todos[0], "skill", "") == "search_web":
            tt = "action"
            if ts not in ("running", "new"):
                ts = "running"
        return todos, tt or "action", ts or "running"

    built = build_search_web_query(ut, context_pack)
    if not built:
        return (
            [
                PlanStep(
                    skill="ask_user",
                    args={
                        "question": "請提供要搜尋的具體名稱或關鍵字（目前無法從對話脈絡補全「剛剛那個／喜歡的遊戲」）。",
                        "rationale": "明確網搜但無法從 Context 補全",
                    },
                )
            ],
            "direct_response",
            "waiting_input",
        )

    return (
        [PlanStep(skill="search_web", args={"query": built})],
        "action",
        "running",
    )
