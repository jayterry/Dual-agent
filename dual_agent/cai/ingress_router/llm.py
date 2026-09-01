"""L1 Ingress Intent Router LLM（qwen2.5:3b few-shot JSON）。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.cai.ingress_router.schemas import IngressRouteDecision
from dual_agent.config import OLLAMA_BASE_URL, cai_ingress_model
from dual_agent.llm_json import coerce_llm_text, invoke_and_parse_json

_INGRESS_SYSTEM_PROMPT = """你只輸出單一 JSON 物件，不要 markdown。

你是 CAI 的 Ingress Intent Router：判斷使用者這一輪的**任務類型**與 URL 是「工具參數」還是「待審正文」。

task_type（必填，其一）：
- action：執行任務（搜尋、查天氣、開啟／讀取網址等）；URL 為工具參數
- check：防詐審查（簡訊、連結是否安全、是不是詐騙）；URL 或全文為待審對象
- direct_response：寒暄、身份、無需工具的一般短答
- memory_update：要求記住人名關係（我媽媽叫…、記住…）
- unknown：無法判斷

requires_dai（bool）：
- true：已有可送 DAI 審查的正文或連結，且使用者意在審查風險
- false：執行 action、閒聊、或僅宣告收到簡訊尚無正文

artifact_role（必填，其一）：
- none：無送審正文；URL 僅作開啟／搜尋參數
- artifact：整句或連結為待審內容（requires_dai 通常 true）
- pending_review：有審查意圖但尚無正文（requires_dai false）

規則：
1. 複合句「查天氣再開 https://…」→ action，requires_dai=false，artifact_role=none
2. 純 URL 或「打開 https://…」→ action，URL 為工具參數
3. 「幫我確認連結安不安全／是不是詐騙」+ URL → check，requires_dai=true，artifact_role=artifact
4. 「我收到一則簡訊」無正文 → check，requires_dai=false，artifact_role=pending_review
5. 【銀行】釣魚簡訊含 URL → check，requires_dai=true，artifact_role=artifact
6. 「我媽媽叫 Yuri／兒子叫小明」→ memory_update（純記人名）；若要求記住金額／匯款則非 memory
7. 「兒子／熟人發訊息叫我投資／匯款／準備房產證」→ check（防詐敘事），requires_dai=true，artifact_role=artifact；**不是** memory_update
8. confidence 0.0–1.0；確定 ≥0.85；模糊降低
9. reason 簡短（除錯用）

JSON 必含鍵：task_type, requires_dai, artifact_role, confidence, reason。

範例（僅供格式參考）：
{few_shot}"""


_FEW_SHOT = json.dumps(
    [
        {
            "input": "搜尋台北天氣，再開 https://github.com",
            "output": {
                "task_type": "action",
                "requires_dai": False,
                "artifact_role": "none",
                "confidence": 0.92,
                "reason": "compound_weather_open_url",
            },
        },
        {
            "input": "https://github.com",
            "output": {
                "task_type": "action",
                "requires_dai": False,
                "artifact_role": "none",
                "confidence": 0.88,
                "reason": "bare_url_open_intent",
            },
        },
        {
            "input": "幫我確認這個連結安不安全：https://bit.ly/abc",
            "output": {
                "task_type": "check",
                "requires_dai": True,
                "artifact_role": "artifact",
                "confidence": 0.9,
                "reason": "link_safety_review",
            },
        },
        {
            "input": "【XX銀行】您的帳戶異常，請點擊 https://fake.com 完成驗證",
            "output": {
                "task_type": "check",
                "requires_dai": True,
                "artifact_role": "artifact",
                "confidence": 0.95,
                "reason": "phishing_sms_body",
            },
        },
        {
            "input": "我兒子叫小明",
            "output": {
                "task_type": "memory_update",
                "requires_dai": False,
                "artifact_role": "none",
                "confidence": 0.93,
                "reason": "remember_child_name",
            },
        },
        {
            "input": "我兒子發訊息跟我說要拿300萬去投資，要我把房產證準備好",
            "output": {
                "task_type": "check",
                "requires_dai": True,
                "artifact_role": "artifact",
                "confidence": 0.94,
                "reason": "family_investment_scam_narrative",
            },
        },
    ],
    ensure_ascii=False,
    indent=2,
)


def _coerce_route_decision(obj: dict[str, Any]) -> IngressRouteDecision | None:
    if not isinstance(obj, dict):
        return None
    task_type = coerce_llm_text(obj.get("task_type")).lower()
    valid = {"action", "check", "direct_response", "memory_update", "unknown"}
    if task_type not in valid:
        return None
    role = coerce_llm_text(obj.get("artifact_role")).lower()
    if role not in ("none", "artifact", "pending_review"):
        role = "none"
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    requires_dai = bool(obj.get("requires_dai"))
    if task_type == "action":
        requires_dai = False
    return IngressRouteDecision(
        task_type=task_type,  # type: ignore[arg-type]
        requires_dai=requires_dai,
        artifact_role=role,  # type: ignore[arg-type]
        confidence=conf,
        reason=coerce_llm_text(obj.get("reason")),
    )


def invoke_ingress_route_llm(
    user_text: str,
    *,
    entities_summary: str = "",
    model: str | None = None,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.0,
) -> IngressRouteDecision | None:
    text = (user_text or "").strip()
    if not text or len(text) > 600:
        return None

    route_model = model or cai_ingress_model()
    human = "使用者訊息：\n{user_text}"
    if entities_summary:
        human = "已抽取實體（參考）：\n{entities_summary}\n\n" + human

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _INGRESS_SYSTEM_PROMPT),
            ("human", human),
        ]
    )
    llm = ChatOllama(model=route_model, base_url=base_url, temperature=temperature)
    chain = prompt | llm | StrOutputParser()
    vars_in = {
        "few_shot": _FEW_SHOT,
        "user_text": text,
        "entities_summary": entities_summary,
    }

    def _invoke() -> str:
        return chain.invoke(vars_in)

    def _retry() -> str:
        retry = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "只輸出 JSON：task_type, requires_dai, artifact_role, confidence, reason。"
                    " task_type 為 action|check|direct_response|memory_update|unknown。",
                ),
                ("human", human),
            ]
        )
        return (retry | llm | StrOutputParser()).invoke(vars_in)

    try:
        obj = invoke_and_parse_json(_invoke, retry_invoke=_retry)
    except (ValueError, KeyError, TypeError, OSError):
        return None
    except Exception:
        return None
    return _coerce_route_decision(obj)
