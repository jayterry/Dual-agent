"""語意層：僅補 H/I 與人話解釋；不從零評分、不捏造外部檢測。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.llm_json import coerce_llm_text, extract_json_object


def _clamp(n: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(n)))


def _urgency_only(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if not re.search(r"緊急|立即|馬上|截止|期限|否則|凍結", t):
        return False
    # 無其他實質特徵
    if re.search(r"http|https|密碼|驗證碼|匯款|轉帳|身分證|銀行", t, re.I):
        return False
    return True


def invoke_semantic_supplement(
    *,
    payload: dict[str, Any],
    component_scores: dict[str, int],
    missing_evidence: list[str],
    machine_tier12_hit: bool,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """
    回傳 r_llm_optional（0–32 建議上限）、explanation、safety_summary、labels。
    關閉：DAI_SEMANTIC_LLM=0 或 enabled=False。
    """
    if enabled is False or os.environ.get("DAI_SEMANTIC_LLM", "1").strip().lower() in ("0", "false", "no"):
        return {
            "r_llm_optional": 0,
            "tier_h": 0,
            "tier_i": 0,
            "explanation": "",
            "safety_summary": "",
            "labels": [],
            "skipped": True,
        }

    text = str(payload.get("text") or "")
    if _urgency_only(text) and not machine_tier12_hit:
        return {
            "r_llm_optional": 0,
            "tier_h": 0,
            "tier_i": 0,
            "explanation": "僅緊急語氣，無 Tier1/2 機器證據，語意層不加分。",
            "safety_summary": "訊息含緊迫用語，但未檢出密碼/OTP/惡意 URL 等硬證據，請保持警覺。",
            "labels": ["urgency_only_no_tier12"],
            "skipped": False,
        }

    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
    llm = ChatOllama(model=m, base_url=u, temperature=temperature, format="json")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
你是 DAI 語意補充層（非主評分）。機器已算好 component_scores，你不得改寫或重算 r_rules、r_threat_intel、r_tls、r_toxic_fused。

你只能：
1) 評估 H：台灣詐騙框架（政府補助、物流、銀行異常、欠費、投資/OTP 等），輸出 tier_h 0–20 與一句 quote。
2) 評估 I：繁簡混用、錯字群聚，輸出 tier_i 0–12。
3) 撰寫 explanation、safety_summary（繁體中文、<=400 字），整合既有分項，勿捏造 threat intel / TLS / sender 技術欄位。
4) missing_evidence 中的項目不得假裝已有結果。

若 component_scores 的 Tier1/2 機器分皆低且僅緊急語氣，tier_h 與 tier_i 必須 <=5，r_llm_optional 必須 <=5。

輸出 JSON：
{{
  "tier_h": 0-20,
  "tier_i": 0-12,
  "r_llm_optional": 0-32,
  "explanation": "...",
  "safety_summary": "...",
  "labels": ["..."],
  "quotes": [{{"tier":"H|I","text":"..."}}]
}}
""".strip(),
            ),
            (
                "human",
                "payload={payload_json}\ncomponent_scores={scores_json}\nmissing_evidence={missing_json}",
            ),
        ]
    )
    try:
        raw = (prompt | llm | StrOutputParser()).invoke(
            {
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "scores_json": json.dumps(component_scores, ensure_ascii=False),
                "missing_json": json.dumps(missing_evidence, ensure_ascii=False),
            }
        )
        obj = extract_json_object(raw)
    except Exception:
        obj = {}

    tier_h = _clamp(int(obj.get("tier_h") or 0), 0, 20)
    tier_i = _clamp(int(obj.get("tier_i") or 0), 0, 12)
    r_llm = _clamp(int(obj.get("r_llm_optional") or (tier_h + tier_i)), 0, 32)
    if not machine_tier12_hit and _urgency_only(text):
        r_llm = min(r_llm, 5)
        tier_h = min(tier_h, 5)
        tier_i = min(tier_i, 5)

    return {
        "r_llm_optional": r_llm,
        "tier_h": tier_h,
        "tier_i": tier_i,
        "explanation": coerce_llm_text(obj.get("explanation")),
        "safety_summary": coerce_llm_text(obj.get("safety_summary")),
        "labels": [str(x) for x in (obj.get("labels") or []) if str(x).strip()],
        "quotes": obj.get("quotes") if isinstance(obj.get("quotes"), list) else [],
        "skipped": False,
    }
