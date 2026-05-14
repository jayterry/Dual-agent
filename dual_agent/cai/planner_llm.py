"""Planner LLM：依流程圖判斷 task_type、task_state、初始 Todo 佇列。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.llm_json import coerce_llm_text, extract_json_object
from dual_agent.cai.planner_context import (
    apply_explicit_search_guard,
    collapse_redundant_search_web,
    dedupe_search_web_in_plan,
    sanitize_search_web_query_string,
    strip_planner_system_prefix,
)
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.schemas import PlanStep, PlannerOutput
from dual_agent.cai.task_taxonomy import normalize_task_type


def _sanitize_and_collapse_search_steps(todos: list[PlanStep]) -> list[PlanStep]:
    """清理 search_web query 內誤抄的系統字樣，並合併連續重複的 search_web。"""
    out: list[PlanStep] = []
    for st in todos:
        if st.skill != "search_web":
            out.append(st)
            continue
        q = sanitize_search_web_query_string(str((st.args or {}).get("query") or ""))
        if q:
            out.append(PlanStep(skill="search_web", args={"query": q}))
    out = collapse_redundant_search_web(out)
    return dedupe_search_web_in_plan(out)


def invoke_planner(
    *,
    user_text: str,
    source_turn_text: str | None = None,
    tool_catalog: list[dict[str, Any]],
    model: str,
    base_url: str,
    temperature: float = 0.2,
    context_pack: str | None = None,
    ingress_summary: str | None = None,
    ingress_detected_task_type: str = "",
    ingress_artifact_text: str = "",
    pending_review: bool = False,
) -> PlannerOutput:
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)
    catalog_json = json.dumps(tool_catalog, ensure_ascii=False)
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
你是 CAI 的「Planner」：只輸出一段 JSON（不要 markdown、不要註解、不要程式碼區塊）。

【CAI 定位：任務導向 Agent（Task-Oriented）】
- CAI **不是**通用聊天機器人；請避免長篇陪聊與無任務主題的閒談。
- **`direct_response`**：**不是**「開放式聊天」代名詞；它表示「**本輪不需工具、不進 Executor**，仍屬**可交付的對答任務**」，由後續 Replan 產出**簡短**回答。
- 若使用者話題與可執行任務無關（例如「你喜歡吃什麼」）：請 **`todos=[]`**、`task_type=direct_response`，並在 **`message`** 說明：禮貌一句＋**引導提出任務**（如協助檢視內容風險、查資料、開連結、整理重點），**不要**像一般 chatbot 延伸閒聊。

【任務分類對照（示例）】
- 「你可以做什麼？」→ `direct_response`，`todos=[]`
- 「幫我看簡訊／審簡訊／是不是詐騙簡訊」→ `check`：僅在**本輪原句已含可審查的簡訊正文**（或 Context 已明確貼過全文）時，排**單一** `call_dai`，`args.artifact`＝該正文、`args.user_text`＝本輪意圖短句（可空）。若原句僅為「我收到一則簡訊」「幫我看簡訊」等**未附內文**的宣告，**禁止** `call_dai`（勿把該句當 artifact）；改為**單一** `ask_user`，`args.question` 請使用者貼上**完整簡訊全文**（可加 `rationale` 簡述為何需要）。
- `call_dai` 的 `args.context_pack`：除非 catalog 另有要求，**請留空**；**禁止**把整段 Context Pack 複製進 `call_dai` 的 args。
- 「搜尋我喜歡的遊戲」→ `action`，`search_web`
- 「真的嗎？」「你怎麼知道？」→ `direct_response`（接續釐清），通常 `todos=[]`
- 「打開某網址」→ `action`，`open_url_readonly` 等
- 「這是不是詐騙？」→ `check`（依 catalog 排適當技能）

【三重輸入：如何一起用來排任務】
你會在 human 訊息看到三塊，職責如下（**缺一不可、也不可混用**）：
1) **Context Pack**：長期摘要＋最近對話＋上一輪任務狀態。用途：**指涉還原**（「我喜歡的遊戲」→ 具體名稱）、**多輪一致性**、**補齊工具參數**。**不是**本輪「使用者一句話」的全文替代。
2) **本輪 Planner 輸入（含銜接）**：可能含 `【接續上一輪】…` 與本輪內容。用途：**理解語境與銜接**（為何延續、先前問了什麼）。**禁止**把此塊原文整段抄進 `search_web.query` 或任何 args。
3) **本輪使用者原句（任務主鍵）**：僅本輪使用者打的那一句／一段（不含系統接續頭）。用途：**判定本輪要做什麼**、**從此抽取工具參數的主幹**（例如搜尋主題、網址、檔名關鍵字）。若與 Context 合併才能執行（指涉詞），則在 args 中寫入**已解析**的具體值，而非整段脈絡。

排 `todos` 時請自檢：**每一筆 skill 的 args 是否都能僅用「原句＋Context 補全後」在 Executor 執行**，避免空泛或貼上系統提示文字。

【Ingress Normalize（系統前處理）】
- human 區塊另會提供一份 **IngressPayload 摘要**，這是**進入 Planner 前**由 deterministic 程式先做的結構化結果。
- **禁止**用欄位名稱 `user_prompt` / `user_text` 來判斷要不要送審；是否屬審查任務，請只看 `artifact_text`、`review_scope`、`input_origin`、`requires_dai`、`detected_task_type`。
- 若 `requires_dai=true` 且 `artifact_text` 非空：優先規劃風險審查；若 catalog 有 `call_dai`，可排 `call_dai`，並將 `artifact` 設為 `artifact_text`。可保留未來欄位如 `input_origin`、`review_scope`、`message_source`。
- 若 `detected_task_type=check` 但 `artifact_text` 為空：**不要**猜測內容、**不要**把意圖句當 artifact；改排單一 `ask_user`，請使用者貼上待審內容。
- 威脅簡訊、恐嚇、綁架、勒索、要求付款等屬於 **check / review 任務**，**不得優先排 `search_web`**。
- 若系統標記 `pending_review=true`：表示正在等待使用者補上待審正文；此時**只能**延續審查流程（通常為 `ask_user`，或正文到位時轉 `call_dai`），**禁止**漂移到 `search_web` 或一般聊天結束。
- 若 `review_scope=none` 且 `detected_task_type=direct_response`：`todos=[]`，走一般任務對答。

【本輪規劃輸入】在 human 區塊中分三欄呈現：Context Pack、本輪 Planner 輸入（含銜接）、本輪使用者原句（任務主鍵）。
1) **本輪規劃輸入**的明確意圖**優先於** Context Pack：不可因脈絡裡已有答案就略過本輪要求的工具。
2) Context Pack 用於**補全工具參數**（例如把「我喜歡的遊戲」對應到脈絡中的具體遊戲名），**不可**用來**取消**本輪已明確要求的搜尋／開啟網頁等動作。
2a) 僅問**天氣、氣溫、降雨、風力**等：優先**單一** `weather`，`args.location` 為具體地點或機場代碼（可從 Context Pack 還原）；**不要**再為同一地點連排多筆 `search_web` 重查天氣。
2b) 「某某是什麼／誰是誰」等短條目、且使用者**未**明文要求「搜尋／上網／google」：可**先**一筆 `instant_answer`（`args.query`）；若 catalog 無此 skill 或情境需要開分頁再搜，再用 `search_web`。
2c) 使用者給了**明確 http(s) 網址**且要**讀取頁面內容／摘要／核對原文**（非僅「幫我開網頁」）：優先 `fetch_url`（`args.url`）；若只需開分頁則用 `open_url_readonly`。**不要**用 `search_web` 代替讀取已知 URL。
3) 若本輪**明文**要求**搜尋／查詢／上網查／上網找／幫我搜／google**等（要開搜尋結果頁），**必須**在 todos **最前面**產生一筆 `search_web`，`args.query` 須為可下關鍵字搜尋的具體字串。**禁止**把「【接續上一輪】…」等系統接續字樣抄入 `query`；接續脈絡只供理解，query 僅用使用者實質需求（如：地名、產品名）。若同時需要「路線＋天氣」等**同一趟資訊需求**，請**合併為單一** `search_web`（用空格串關鍵字），**禁止**連排多筆語意重疊的 `search_web`（含簡繁寫出兩次同一查詢）。**注意**：天氣本身請用規則 2a 的 `weather`，不要把「查天氣」誤當成一定要 `search_web`。
4) 若 `query` 須表達的主體出現**指涉詞**（如「我喜歡的」「剛剛那個」「前面那則」「喜歡的遊戲」「那個遊戲」等），應從 Context Pack **補全成具體名稱**再寫入 query；**不要**把未解析的指涉詞原封不動當成唯一 query。
5) 若無法從 Context Pack 補全指涉、又必須搜尋，則改為**單一** `ask_user` todo，詢問缺少的具體名稱或關鍵字（**不要**空 query 硬搜）。
6) **「我喜歡的遊戲是什麼？」**這類純問句（問事實、未要求上網查）→ `task_type=direct_response`，`task_state=answering`，**`todos=[]`**。
7) **「搜尋我喜歡的遊戲」**這類明確網搜 → `task_type=action`，`task_state=running`，**todos 第一筆必為 `search_web`**，且 `args.query` 須依規則 4 補全為具體關鍵字。

其他規則：
- 「什麼是…」「解釋…」「介紹…」等僅概念說明、且**未**出現規則 3 的網搜動詞：**todos=[]**；不要自動為「查百科」而加 search_web。
- 需要開網址、開程式等：從 tool catalog 選正確 skill。
- 詢問「助理／你本人／Replan／CAI 能做什麼、有哪些任務、自我介紹名字」或短句確認（如「真的嗎」）：屬 **`direct_response` 任務**，**`todos` 必須為 []**，**禁止** `search_web`；在 `message` 簡述理由（例如：使用者詢問助理能力，屬不需工具之任務對答）。
- 詢問「我是誰」「你是誰」「我媽媽叫什麼」等**身份／關係／名稱回憶**問題時，若 `Context Pack` 已有明說事實，應維持 **`direct_response`**、`todos=[]`，交由後續 Replan 直接依脈絡回答；**不要**因為是人物問題就優先 `ask_user`。
- 若 `Context Pack` 對同一身份或稱呼有多個版本，請以**較新的使用者明確更正**為準；舊稱呼或較早輪次內容不可覆蓋新版本。

可用技能（JSON）：{tool_catalog_json}

task_type 必須為以下之一：**direct_response** | **action** | **check** | **unknown**（**不要**使用 general_qa；若你習慣舊稱請在內心對應到 direct_response）。

輸出 JSON 鍵名必須完全一致：
{{ "task_type": "...", "task_state": "...", "todos": [ ... ], "message": "..." }}

若你要在字串內示範大括號，請用雙大括號轉義。
""".strip(),
            ),
            (
                "human",
                """【對話與任務脈絡（Context Pack）】
{context_pack}

【IngressPayload 摘要（系統前處理結果）】
{ingress_summary}

【本輪 Planner 輸入（含「接續上一輪」銜接；供理解語境）】
{user}

【本輪使用者原句（任務主鍵：請優先依此句判定意圖並撰寫工具 args；指涉詞請用 Context Pack 補成具體值）】
{source_turn}""",
            ),
        ]
    )
    source_turn_display = (source_turn_text or "").strip() or strip_planner_system_prefix(user_text.strip())
    raw = (prompt | llm | StrOutputParser()).invoke(
        {
            "user": user_text.strip(),
            "source_turn": source_turn_display or "（無）",
            "tool_catalog_json": catalog_json,
            "context_pack": (context_pack or "").strip() or "（無）",
            "ingress_summary": (ingress_summary or "").strip() or "（無）",
        }
    )
    obj = extract_json_object(raw)

    task_type = normalize_task_type(coerce_llm_text(obj.get("task_type")))
    task_state = coerce_llm_text(obj.get("task_state")).lower() or "new"
    allowed_ts = ("new", "running", "waiting_input", "completed", "blocked", "answering")
    if task_state not in allowed_ts:
        task_state = "new"

    todos_raw = obj.get("todos") or obj.get("steps") or []
    if not isinstance(todos_raw, list):
        todos_raw = []

    todos: list[PlanStep] = []
    for item in todos_raw:
        if not isinstance(item, dict):
            continue
        sk = coerce_llm_text(item.get("skill")).lower()
        args = item.get("args") or {}
        if not sk:
            continue
        if not isinstance(args, dict):
            args = {}
        todos.append(PlanStep(skill=sk, args={str(k): v for k, v in args.items()}))

    todos = _sanitize_and_collapse_search_steps(todos)
    intent = source_turn_display

    message = coerce_llm_text(obj.get("message"))
    todos, task_type, task_state, message = validate_planner_output(
        user_text=intent,
        task_type=task_type,
        task_state=task_state,
        todos=todos,
        message=message,
        ingress_detected_task_type=ingress_detected_task_type,
        ingress_artifact_text=ingress_artifact_text,
        pending_review=pending_review,
    )
    todos, task_type, task_state = apply_explicit_search_guard(
        user_text=intent,
        context_pack=context_pack,
        todos=todos,
        task_type=task_type,
        task_state=task_state,
    )
    return PlannerOutput(task_type=task_type, task_state=task_state, todos=todos, message=message)
