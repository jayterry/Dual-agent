"""Replan LLM：依執行結果／剩餘待辦決定完成、最終回答、更新佇列或等待使用者輸入。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.llm_json import coerce_llm_bool, coerce_llm_text, extract_json_object
from dual_agent.cai.planner_context import post_process_replan_todos
from dual_agent.cai.schemas import PlanStep, ReplanOutput


def invoke_replan(
    *,
    user_text: str,
    task_type: str,
    task_state: str,
    remaining_todos: list[PlanStep],
    observation_log: str | None,
    planner_message: str,
    model: str,
    base_url: str,
    temperature: float = 0.2,
    context_pack: str | None = None,
    pending_review: bool = False,
) -> ReplanOutput:
    llm = ChatOllama(model=model, base_url=base_url, temperature=temperature)

    def _todo_json(steps: list[PlanStep]) -> str:
        return json.dumps(
            [{"skill": s.skill, "args": s.args} for s in steps],
            ensure_ascii=False,
        )

    obs = (observation_log or "").strip() or "（尚無執行結果）"
    preamble = (planner_message or "").strip()

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
你是 CAI 的「Replan」：只輸出一段 JSON（不要 markdown、不要註解、不要程式碼區塊）。

你會收到：
- 「對話與任務脈絡」：長期摘要、最近對話、上一輪任務狀態（可能為「無」）；請用於多輪一致性。
- 使用者原始需求
- Planner 設定的 task_type、task_state（**direct_response** 表示本輪無工具待辦、不進 Executor，回答應**簡短**且**任務導向**，避免當成開放式聊天）
- 規劃時已區分：**Context Pack**（脈絡）、**含銜接的 Planner 輸入**（語境）、**本輪使用者原句**（任務主鍵）；你的 `final_answer` 應與三者一致，**不要**與本輪主鍵矛盾或無視已成功 observation
- Planner 的簡短說明（可能為空）
- 目前「尚未執行」的待辦佇列 remaining_todos（JSON）
- **執行紀錄 observation_log**：可能包含多段「第 N 次 Executor」結果，請一併閱讀；不要忽略前幾次已成功完成的 search_web / open_url / fetch_url / weather / instant_answer。

【語言】`final_answer` 必須以**繁體中文**撰寫（原文引用、URL、商標、專有名詞原文除外）。**禁止**在句中夾雜英文一般詞彙（例如 \"Authorities\"、\"Please confirm\"）；若指執法單位請寫「警方」「主管機關」等中文慣用說法。

【search_web 特別說明】若 observation 顯示 `search_web` **僅**「已開啟搜尋」或**僅**含搜尋 URL、而**沒有**任何網頁正文／搜尋結果摘要，代表助理**尚未讀取**結果頁內容：`final_answer` **不得**假裝已看過搜尋結果，也**不得**虛構條目細節（地址、營業項目、觀光體驗、歷史沿革等）。應簡短說明已在瀏覽器開啟搜尋、請使用者自行查閱分頁；若需要口頭摘要，可一句話建議使用者貼上**官方網址**以便後續用 `fetch_url` 讀正文（**不要**在無正文時硬寫百科式介紹）。

【call_dai／簡訊審查】若 observation 含 `call_dai` 或摘要前綴 **[DAI]**：請以紀錄中的風險分數、`safety_summary`、主要原因（如 `reason_highlights`、evidence、defense observation 摘要）與建議動作為準整合回答，**不要**自創未出現在紀錄中的法律後果或機關名稱細節。若紀錄已提供風險分數，`final_answer` 應明確寫出「風險分數 XX/100」，並簡短列出 1-3 個主要原因給使用者看。

【絕對禁止捏造審核分數】若 observation_log **不包含** **`call_dai` 的成功執行摘要**（或不含 **[DAI]**、不含任何由 DAI／工具回傳的風險分數紀錄），則 **`final_answer` 不得**書寫「風險分數」「xx/100」「已審查完成」「審核結果為…分」等審級結論；應請使用者貼上完整待審內容或使用送審，或說明目前無法評分。

【已審完成、本輪無 call_dai（請讀 Context【上一輪任務狀態】）】
- 若工作狀態顯示已審完成且本輪未再跑 DAI：依 `message_source`、分數與摘要**簡短**作答（1–4 句），勿重述整份風險報告。
- 「我是誰」→ 只答使用者稱呼（【長期記憶】display_name），一句話；勿夾帶助理自我介紹。
- 「你是誰」→ CAI 行動安全助理；若搞混稱呼可自然區分，勿用考試式糾正語氣。

【人物名稱與關係事實】
- **「我是誰」與「你是誰」不可混淆**：前者只答使用者稱呼；後者只答助理身份。使用者自稱的名字**不得**當成助理名字（禁止「我是您的智能助理 Alex」）。答「我是誰」時**不要**順便否定「我是某某」——那句只適用於使用者問「你是某某嗎」時。
- 若 `Context Pack` 已明說人物名稱、關係或稱呼（例如「我叫 Terry」「你現在叫 CAI」「我媽媽叫 mei」），回答此類問題時應**直接引用已知事實**，不要退化成泛稱（例如只說「你的母親」）。
- 若 `Context Pack` 對同一事實有多個版本，**以較新的「使用者明確更正」為準**；較早輪次的舊稱呼、助理先前自稱或模糊說法，不得覆蓋使用者後來的更正。
- 只有在 `Context Pack` 中**真的沒有**足夠事實時，才可回答不知道、請使用者補充或再次確認。

【review pending】
- 若 `pending_review=true`：表示系統已判定這是一個審查事件，可能仍在等待待審正文。
- 在 `pending_review=true` 時，**不得**改排 `search_web`，也**不得**用一般安撫式回答結束任務。
- 若尚未取得正文：通常應追問使用者貼上簡訊／訊息內容。
- 若 **observation 尚無 `call_dai`**，但本輪使用者原句**看似**已貼上摘錄（具體金額、借還款、威脅語等）：**不要**只重複「請貼全文」而無視內容；應 **complete=false**，在 **updated_todos** 第 0 筆排 `call_dai`，`args.artifact`＝本輪原句（除非明顯是閒聊／天氣等新話題）。
- 若正文已齊備：應維持在審查流程中，交由 `call_dai` / risk_analysis，而不是退回一般聊天。

你的職責：
1) 若已可回覆使用者：complete=true，final_answer 填繁體中文完整回答；updated_todos 必須為 []；task_state 可為 "completed" 或 "answering"。
2) 若仍需執行後續步驟：complete=false，updated_todos 為「下一步起」的有效佇列（下一個要執行的在陣列第 0 筆）；final_answer 可為空字串。
3) 若必須先向使用者要資料：waiting_input=true，user_prompt 填要顯示給使用者的問題（簡短）；complete=false；updated_todos 可保留待續或清空由你判斷。

【避免重複工具】若 observation_log 已顯示 **open_url、fetch_url、weather 或 instant_answer 成功（OK）**，且足以回答使用者當下問題；或 **search_web 成功（OK）且紀錄中已含可引用的正文／摘要**（非僅「已開啟搜尋」一行）且足以回答：
- 你必須 **complete=true**，在 **final_answer** 整合工具結果並回答。
- **updated_todos 必須為 []**；禁止再把「同一意圖」的 search_web／open_url／fetch_url／weather／instant_answer 排進佇列，除非使用者原文明確要求「再搜一次／多搜幾個」。
- 若 remaining_todos 含多筆 **語意重複** 的 `search_web`（僅簡繁或標點不同），應視為同一查詢，只保留一筆或改為 **complete=true** 用既有 observation 回答。

【硬性規則】當 remaining_todos 為 **空陣列 []** 且 observation_log 為「（尚無執行結果）」或僅為占位：
- 若使用者訊息**明文要求網路搜尋／查詢**（含：搜尋、幫我搜、查詢、查查、上網查、上網找、「用 Google 搜」等）：**不得**僅依 Context Pack 用 final_answer 代替搜尋；必須 **complete=false**，**updated_todos** 第 0 筆為 `search_web` 且 `args.query` 具體可搜。**例外**：「打開 Google／開啟 google.com」是**開首頁** → 用 `open_url_readonly`，**禁止** `search_web`；若 observation 已有 **OK** 的 `open_url_readonly` 或 `search_web`（已開啟），必須 **complete=true**、**updated_todos=[]**，勿重複執行。
- 否則（一般問答／解釋題）：你必須 **complete=true**，在 **final_answer** 直接回答使用者（繁體中文）。
- 上述「一般問答」情況下 **updated_todos 必須為 []**；禁止為了「查百科」而塞入 search_web / open_url / open_app，除非已符合上一條「明文網搜」。

【無工具結果時的 final_answer（防「步驟 0 卻像已搜尋」）】
當 observation_log **尚無**任何 **OK** 的 search_web／open_url／fetch_url／weather／instant_answer 等工具結果時；或 **僅**有 **OK** 的 `search_web` 但內容僅「已開啟搜尋」而無正文（此時視同無可引用網搜結果，並遵守【search_web 特別說明】）：
- final_answer **不可**寫成長篇「百科／維基式」條目；**禁止**加入使用者與 Context Pack **都未明確寫出**的具體聲稱（例如開發商全名、發行年份、遊戲類型標籤、引擎名等）。**禁止**臆測或錯配遊戲類型（例如把大逃殺說成 MOBA）。
- 若使用者是**確認偏好、反問、聊天語氣**（如「我不是喜歡 ○○ 嗎」「我喜歡 ○○ 吧？」）：以**簡短**呼應為主（一兩句）；若要考據級介紹，請在結尾**一句**提醒可說「搜尋 ○○」或「介紹 ○○」。
- 若使用者**明確**要介紹／什麼是／解釋某主題但仍無工具結果：可適度說明，但仍須遵守上一段「不捏造未出現的硬事實」；細節不足時請坦承並建議搜尋。

task_state 必須為以下之一：new | running | waiting_input | completed | blocked | answering

輸出 JSON 鍵名必須一致：
{{
  "complete": true/false,
  "final_answer": "字串",
  "updated_todos": [ {{ "skill": "...", "args": {{}} }} ],
  "task_state": "...",
  "waiting_input": true/false,
  "user_prompt": "字串"
}}
""".strip(),
            ),
            (
                "human",
                """【對話與任務脈絡（Context Pack）】
{context_pack}

使用者訊息：
{user_text}

task_type={task_type}
task_state={task_state}
pending_review={pending_review}

Planner 說明：
{preamble}

remaining_todos（JSON）：
{remaining_json}

執行紀錄 observation_log（依時間排序；可能多段）：
{obs}
""".strip(),
            ),
        ]
    )
    raw = (prompt | llm | StrOutputParser()).invoke(
        {
            "context_pack": (context_pack or "").strip() or "（無）",
            "user_text": user_text.strip(),
            "task_type": task_type,
            "task_state": task_state,
            "pending_review": "true" if pending_review else "false",
            "preamble": preamble or "（無）",
            "remaining_json": _todo_json(remaining_todos),
            "obs": obs,
        }
    )
    obj = extract_json_object(raw)

    complete = coerce_llm_bool(obj.get("complete"))
    final_answer = coerce_llm_text(obj.get("final_answer"))
    waiting_input = coerce_llm_bool(obj.get("waiting_input"))
    user_prompt = coerce_llm_text(obj.get("user_prompt"))
    task_state_out = coerce_llm_text(obj.get("task_state")).lower() or task_state
    allowed_ts = ("new", "running", "waiting_input", "completed", "blocked", "answering")
    if task_state_out not in allowed_ts:
        task_state_out = task_state

    raw_todos = obj.get("updated_todos") or obj.get("todos") or []
    if not isinstance(raw_todos, list):
        raw_todos = []

    updated: list[PlanStep] = []
    for item in raw_todos:
        if not isinstance(item, dict):
            continue
        sk = coerce_llm_text(item.get("skill")).lower()
        args = item.get("args") or {}
        if not sk:
            continue
        if not isinstance(args, dict):
            args = {}
        updated.append(PlanStep(skill=sk, args={str(k): v for k, v in args.items()}))

    updated = post_process_replan_todos(
        user_text=user_text,
        observation_log=observation_log,
        todos=updated,
    )

    return ReplanOutput(
        complete=complete,
        final_answer=final_answer,
        updated_todos=updated,
        task_state=task_state_out,
        waiting_input=waiting_input,
        user_prompt=user_prompt,
    )
