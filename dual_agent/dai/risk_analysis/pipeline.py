"""run_risk_analysis：機器層 + 語意補充 + UEBA。"""

from __future__ import annotations

from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.risk_analysis.payload import build_analysis_payload, text_for_analysis
from dual_agent.dai.risk_analysis.providers import (
    build_tls_findings,
    build_url_threat_hits,
    collect_missing_evidence,
    score_r_threat_intel,
    score_r_tls,
)
from dual_agent.dai.risk_analysis.rules import rules_hits_to_dict, score_r_rules
from dual_agent.dai.risk_analysis.semantic_llm import invoke_semantic_supplement
from dual_agent.dai.risk_analysis.toxic_score import compute_r_toxic_fused
from dual_agent.dai.risk_analysis.verdict import (
    apply_ueba_to_display_score,
    dominant_source,
    recommended_cai_action,
    verdict_from_score,
)
from dual_agent.dai.schemas import DAIRequest
from dual_agent.dai.user_db import apply_ueba_to_report, compute_user_risk


def _machine_tier12_hit(scores: dict[str, int]) -> bool:
    for k in ("r_rules", "r_threat_intel", "r_tls", "r_toxic_fused"):
        if int(scores.get(k) or 0) >= 50:
            return True
    return False


def run_risk_analysis(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
    url_threat_hits_injected: list[dict[str, Any]] | None = None,
    tls_findings_injected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = text_for_analysis(req)
    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
    src = (source or "desktop").strip() or "unknown"

    payload = build_analysis_payload(req)
    urls_from_text = list(payload.get("urls") or [])

    url_threat_hits = build_url_threat_hits(urls_from_text, injected=url_threat_hits_injected)
    tls_findings = build_tls_findings(urls_from_text, injected=tls_findings_injected)
    payload["url_threat_hits"] = url_threat_hits
    payload["tls_findings"] = tls_findings

    rules_res = score_r_rules(text)
    r_rules = rules_res.score
    r_threat_intel, ti_evidence = score_r_threat_intel(url_threat_hits)
    r_tls, tls_evidence = score_r_tls(tls_findings)
    r_toxic_fused, toxic_meta = compute_r_toxic_fused(text, model=m, base_url=u)

    missing = collect_missing_evidence(
        urls=urls_from_text,
        url_threat_hits=url_threat_hits,
        tls_findings=tls_findings,
        sender_tech_context=payload.get("sender_tech_context") or {},
    )

    component_scores: dict[str, int] = {
        "r_rules": r_rules,
        "r_threat_intel": r_threat_intel,
        "r_tls": r_tls,
        "r_toxic_fused": r_toxic_fused,
        "r_llm_optional": 0,
    }
    machine_hit = _machine_tier12_hit(component_scores)

    semantic = invoke_semantic_supplement(
        payload=payload,
        component_scores=component_scores,
        missing_evidence=missing,
        machine_tier12_hit=machine_hit,
        model=m,
        base_url=u,
        temperature=temperature,
    )
    r_llm_optional = int(semantic.get("r_llm_optional") or 0)
    # 語意層單項上限，避免 LLM 輸出異常拉高 max
    r_llm_optional = max(0, min(32, r_llm_optional))
    component_scores["r_llm_optional"] = r_llm_optional

    r_final = max(
        r_rules,
        r_threat_intel,
        r_tls,
        r_toxic_fused,
        r_llm_optional,
    )
    verdict_pre = verdict_from_score(r_final)
    dom = dominant_source({k: v for k, v in component_scores.items() if k != "r_llm_optional"})

    # UEBA：先算 r_ueba 分量（s_user），再調整顯示分
    ur = compute_user_risk(
        text=text,
        source=src,
        llm_verdict=verdict_pre,
        risk_total_fused=r_final,
    )
    r_ueba = int(ur.s_user_0_100)
    component_scores["r_ueba"] = r_ueba

    risk_score = apply_ueba_to_display_score(
        r_final,
        delta_user=int(ur.delta_user),
        r_rules=r_rules,
        r_threat_intel=r_threat_intel,
    )
    verdict = verdict_from_score(risk_score)
    gate_tier = verdict if verdict in ("allow", "warn", "block") else "quarantine"

    evidence: list[dict[str, Any]] = []
    evidence.extend(rules_hits_to_dict(rules_res.hits))
    evidence.extend(ti_evidence)
    evidence.extend(tls_evidence)
    if toxic_meta.get("s_tox", 0):
        evidence.append({"source": "toxic_db", **toxic_meta})
    for q in semantic.get("quotes") or []:
        if isinstance(q, dict):
            evidence.append({"source": "semantic_llm", **q})

    reason_highlights: list[str] = []
    if r_rules >= 25:
        reason_highlights.append(f"硬規則命中（{r_rules} 分）")
    if r_threat_intel >= 15:
        reason_highlights.append(f"URL 威脅情資（{r_threat_intel} 分）")
    if r_tls:
        reason_highlights.append(f"TLS 異常（{r_tls} 分）")
    if r_toxic_fused >= 40:
        reason_highlights.append(f"毒樣相似（{r_toxic_fused} 分）")
    if r_llm_optional:
        reason_highlights.append(f"語意框架/語言品質（{r_llm_optional} 分）")
    expl = str(semantic.get("safety_summary") or semantic.get("explanation") or "").strip()
    if expl and len(reason_highlights) < 3:
        reason_highlights.append(expl[:160])

    track_a = {
        "tier_scores": {
            "H": int(semantic.get("tier_h") or 0),
            "I": int(semantic.get("tier_i") or 0),
        },
        "matched_rules": rules_hits_to_dict(rules_res.hits),
        "missing_evidence": list(missing),
    }

    report: dict[str, Any] = {
        "risk_score": risk_score,
        "risk_score_total": risk_score,
        "r_final_machine": r_final,
        "verdict": verdict,
        "gate_tier": gate_tier,
        "dominant_source": dom,
        "component_scores": component_scores,
        "evidence": evidence,
        "reason_highlights": reason_highlights[:6],
        "track_a": track_a,
        "safety_summary": str(semantic.get("safety_summary") or "").strip() or _fallback_summary(risk_score, verdict),
        "archive_note": (str(semantic.get("explanation") or "")[:80] or f"風險 {risk_score}/100"),
        "labels": list(semantic.get("labels") or []),
        "risk_fusion": {
            "mode": "max_component",
            "r_final": r_final,
            "risk_total": risk_score,
            "toxic": toxic_meta,
        },
        "semantic": semantic,
        "analysis_payload": payload,
        "pipeline_phases": [
            "rules",
            "threat_intel",
            "tls",
            "toxic",
            "semantic_hi",
            "max_merge",
            "ueba",
            "verdict",
        ],
        "recommended_cai_action": recommended_cai_action(verdict, risk_score),
    }

    report_dict = dict(report)
    apply_ueba_to_report(report_dict, text=text, source=src)
    report_dict["risk_score"] = risk_score
    report_dict["risk_score_total_user_fused"] = int(
        report_dict.get("risk_score_total_user_fused") or risk_score
    )
    # 以機器主分為準，UEBA 僅調整；guardrail 已在 apply_ueba_to_display_score
    if max(r_rules, r_threat_intel) >= 85:
        report_dict["risk_score_total_user_fused"] = max(
            int(report_dict["risk_score_total_user_fused"]),
            max(r_rules, r_threat_intel),
            r_final,
        )
        report_dict["risk_score"] = report_dict["risk_score_total_user_fused"]
    return report_dict


def _fallback_summary(score: int, verdict: str) -> str:
    return f"綜合風險 {score}/100，判定 {verdict}。"
