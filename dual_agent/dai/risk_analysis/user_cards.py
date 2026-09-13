"""使用者面向風險卡：線索、情境因素、警示 pill、限制、純文字備援。"""

from __future__ import annotations

import re
from typing import Any

from dual_agent.dai.fraud_dual.gnn.rules import RuleContextScorer
from dual_agent.dai.fraud_dual.shared.features.intent_features import extract_intent_features
from dual_agent.dai.fraud_dual.shared.features.payload_features import extract_payload_features
from dual_agent.dai.fraud_dual.shared.features.rhetoric_features import extract_rhetoric_features
from dual_agent.dai.fraud_dual.shared.schemas import ResultA, SharedFeatures
from dual_agent.dai.risk_analysis.review_display import verdict_display

INSTRUCTION_165 = "請自行開啟官方 App 查證；必要時聯絡 165。"
LIMITATION_PROTOTYPE = (
    "本分析由 AI 自動生成，僅供參考，非法律意見或官方判定；"
    "分數不代表受害機率。請自行向官方或原服務管道查證後再操作，必要時聯絡 165。"
)

_SKIP_FACTORS = frozenset(
    {
        "hetero_gnn",
        "learned_context_model",
        "familiar_trusted_soft_discount",
    }
)

_FACTOR_ZH: dict[str, str] = {
    "unknown_relation": "關係目前為 Unknown",
    "unknown_sender_high_inducement": "陌生來訊且誘因偏高",
    "official_claim_vs_fake_cs": "與目前人設不一致",
    "elder_age": "高齡族群較常被鎖定",
    "elder_high_payload": "高齡加上可疑連結或下載",
    "elder_scam_intent": "高齡加上常見詐騙類型",
    "retired_investment": "退休身分碰上投資誘導",
    "student_loan_or_job": "學生身分碰上貸款或打工誘導",
    "no_invest_exp": "投資經驗不足卻被拉去投資",
    "payload_surface": "訊息帶有可點擊或下載的內容",
    "pressure_from_untrusted_sender": "來路不明還催你趕快處理",
}

_FACTOR_PRIORITY = (
    "unfamiliar_channel",
    "official_claim_vs_fake_cs",
    "unknown_relation",
    "unknown_sender_high_inducement",
    "pressure_from_untrusted_sender",
    "elder_high_payload",
    "elder_scam_intent",
    "retired_investment",
    "student_loan_or_job",
    "no_invest_exp",
    "payload_surface",
    "elder_age",
)


def is_hetero_backend(backend: str) -> bool:
    b = (backend or "").strip().lower()
    return "hetero" in b or "sage" in b or "gnn" in b


def context_card_title(backend: str) -> str:
    return "GNN 情境因素" if is_hetero_backend(backend) else "情境因素"


def build_threat_clues(
    text: str,
    shared: SharedFeatures | None = None,
    *,
    limit: int = 4,
) -> list[str]:
    """從 rhetoric／payload／intent 抽出短標線索。"""
    msg = shared.message_features if shared is not None else extract_rhetoric_features(text)
    pay = shared.payload_features if shared is not None else extract_payload_features(text)
    intent = shared.intent_features if shared is not None else extract_intent_features(text)
    out: list[str] = []

    def add(label: str) -> None:
        if label and label not in out:
            out.append(label)

    if float(msg.urgency_score or 0) >= 0.25:
        add("限時要求")
    if int(pay.url_is_shortener or 0):
        add("短網址")
    if int(pay.contains_apk or 0) or re.search(
        r"下載\s*(app|apk|應用)|安裝\s*(app|apk)|點此下載",
        text,
        flags=re.I,
    ):
        add("下載 App")
    if int(intent.otp_keyword or 0):
        add("要驗證碼")
    if int(pay.contains_url or 0) and "短網址" not in out:
        add("含連結")
    if int(intent.loan_keyword or 0):
        add("貸款話術")
    if float(msg.authority_score or 0) >= 0.3:
        add("自稱官方")
    if float(msg.fear_score or 0) >= 0.3:
        add("恐嚇停權")
    if int(pay.contains_phone or 0):
        add("留聯絡電話")
    if float(msg.reward_score or 0) >= 0.3:
        add("高報酬誘導")
    return out[:limit]


def _explain_signals(
    *,
    shared: SharedFeatures | None,
    persona: dict[str, Any],
    result_a: ResultA,
) -> dict[str, Any]:
    ch_feat = shared.channel_features if shared is not None else None
    msg = shared.message_features if shared is not None else None
    pay = shared.payload_features if shared is not None else None
    apps = list(persona.get("primary_apps") or [])
    channel = str(persona.get("channel") or (ch_feat.channel if ch_feat else "") or "SMS")
    familiar = int(ch_feat.channel_is_familiar) if ch_feat is not None else int(channel in apps)
    return {
        "channel_is_familiar": familiar,
        "relation_type": str(persona.get("relation_type") or "Unknown"),
        "scam_type": str(result_a.scam_type or "Unknown"),
        "age_band": str(persona.get("age_band") or "25-39"),
        "occupation": str(persona.get("occupation") or "other"),
        "reward_score": float(msg.reward_score) if msg is not None else 0.0,
        "urgency_score": float(msg.urgency_score) if msg is not None else 0.0,
        "fear_score": float(msg.fear_score) if msg is not None else 0.0,
        "payload_risk_score": float(pay.payload_risk_score) if pay is not None else 0.0,
        "invest_exp": persona.get("invest_exp"),
        "channel": channel,
    }


def _label_factor(key: str, signals: dict[str, Any]) -> str | None:
    if key in _SKIP_FACTORS:
        return None
    if key == "unfamiliar_channel":
        channel = str(signals.get("channel") or "此管道").strip() or "此管道"
        return f"{channel} 非常用平台"
    return _FACTOR_ZH.get(key)


def build_context_factor_labels(
    *,
    shared: SharedFeatures | None,
    persona: dict[str, Any],
    result_a: ResultA,
    limit: int = 3,
) -> list[str]:
    """分數仍來自 Context scorer；因素用規則可解釋層（不改分數）。"""
    signals = _explain_signals(shared=shared, persona=persona, result_a=result_a)
    pred = RuleContextScorer().predict(signals)
    keyed = [k for k in pred.factors if k not in _SKIP_FACTORS]
    ordered = [k for k in _FACTOR_PRIORITY if k in keyed]
    for k in keyed:
        if k not in ordered:
            ordered.append(k)
    labels: list[str] = []
    for key in ordered:
        label = _label_factor(key, signals)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= limit:
            break
    if not labels and str(signals.get("relation_type") or "") == "Unknown":
        labels.append("關係目前為 Unknown")
    return labels[:limit]


def build_headline(verdict: str, threat_score_100: int) -> str:
    v = verdict_display(verdict)
    if v == "block" or int(threat_score_100) >= 85:
        return "建議先不要點擊或安裝"
    if v == "warn":
        return "先查證再操作"
    return ""


def build_limitations(*, relation: str) -> list[str]:
    """限制格固定免責；relation 保留相容呼叫端。"""
    _ = relation
    return [LIMITATION_PROTOTYPE]


def build_card_suggestions(*, verdict: str, existing: list[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(msg: str) -> None:
        s = (msg or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    v = verdict_display(verdict)
    if v in {"block", "warn"}:
        add("請自行開啟官方 App 查證；必要時聯絡 165。")
    for item in existing or []:
        add(item)
    if not out:
        add("若有疑慮，請向官方或原服務管道查證後再回應")
    return out[:5]


def format_user_display(
    *,
    headline: str,
    instruction: str,
    threat_score_100: int,
    context_score_100: int,
    threat_clues: list[str],
    context_factors: list[str],
    context_backend: str,
    limitations: list[str],
    narrator: str | None,
    suggestions: list[str],
) -> str:
    """聊天純文字備援：警示 → 兩分＋線索 → 限制 → 口語報告。"""
    lines: list[str] = []
    if headline:
        lines.append(headline)
        if instruction:
            lines.append(instruction)
        lines.append("")
    clues = "｜".join(threat_clues) if threat_clues else "—"
    factors = "；".join(context_factors) if context_factors else "—"
    lines.append(f"ML / LLM 訊息線索　{int(threat_score_100)}/100")
    lines.append(clues)
    lines.append("")
    lines.append(f"{context_card_title(context_backend)}　{int(context_score_100)}/100")
    if context_backend and not is_hetero_backend(context_backend):
        lines.append(f"（後端：{context_backend}）")
    lines.append(factors)
    lines.append("")
    lines.append("限制")
    for item in limitations:
        lines.append(item)
    if narrator:
        lines.append("")
        lines.append(str(narrator).strip()[:900])
    if suggestions:
        lines.append("")
        lines.append("建議：")
        for s in suggestions:
            lines.append(f"• {s}")
    return "\n".join(lines).strip()
