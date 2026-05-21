"""DAI DAG 各步驟實作（供 dai/skills 與 executor 共用）。"""

from __future__ import annotations

from typing import Any

from dual_agent.config import dai_risk_llm_weight
from dual_agent.dai.pipeline_context import SMS_REVIEW_DAG, DefensePipelineContext
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
    dominant_source,
    finalize_display_risk_score,
    fuse_risk_score_weighted,
    recommended_cai_action,
    summary_indicates_scam,
    verdict_from_score,
)
from dual_agent.dai.user_db import apply_ueba_to_report, compute_user_risk
from dual_agent.dai.risk_analysis.review_display import enrich_report_display_fields


def _machine_tier12_hit(scores: dict[str, int]) -> bool:
    for k in ("r_rules", "r_threat_intel", "r_tls", "r_toxic_fused"):
        if int(scores.get(k) or 0) >= 50:
            return True
    return False


def step_build_analysis_payload(ctx: DefensePipelineContext) -> None:
    ctx.text = text_for_analysis(ctx.req)
    ctx.payload = build_analysis_payload(ctx.req)
    ctx.urls_from_text = list(ctx.payload.get("urls") or [])
    ctx.url_threat_hits = build_url_threat_hits(
        ctx.urls_from_text, injected=ctx.url_threat_hits_injected
    )
    ctx.tls_findings = build_tls_findings(ctx.urls_from_text, injected=ctx.tls_findings_injected)
    ctx.payload["url_threat_hits"] = ctx.url_threat_hits
    ctx.payload["tls_findings"] = ctx.tls_findings


def step_score_rules(ctx: DefensePipelineContext) -> None:
    ctx.rules_res = score_r_rules(ctx.text)
    ctx.r_rules = ctx.rules_res.score
    ctx.component_scores["r_rules"] = ctx.r_rules


def step_score_threat_intel(ctx: DefensePipelineContext) -> None:
    ctx.r_threat_intel, ctx.ti_evidence = score_r_threat_intel(ctx.url_threat_hits)
    ctx.component_scores["r_threat_intel"] = ctx.r_threat_intel


def step_score_tls(ctx: DefensePipelineContext) -> None:
    ctx.r_tls, ctx.tls_evidence = score_r_tls(ctx.tls_findings)
    ctx.component_scores["r_tls"] = ctx.r_tls
    ctx.missing_evidence = collect_missing_evidence(
        urls=ctx.urls_from_text,
        url_threat_hits=ctx.url_threat_hits,
        tls_findings=ctx.tls_findings,
        sender_tech_context=ctx.payload.get("sender_tech_context") or {},
    )


def step_score_toxic(ctx: DefensePipelineContext) -> None:
    ctx.r_toxic_fused, ctx.toxic_meta = compute_r_toxic_fused(
        ctx.text, model=ctx.model, base_url=ctx.base_url
    )
    ctx.component_scores["r_toxic_fused"] = ctx.r_toxic_fused
    ctx.component_scores.setdefault("r_llm_optional", 0)


def step_semantic_supplement(ctx: DefensePipelineContext) -> None:
    machine_hit = _machine_tier12_hit(ctx.component_scores)
    ctx.semantic = invoke_semantic_supplement(
        payload=ctx.payload,
        component_scores=ctx.component_scores,
        missing_evidence=ctx.missing_evidence,
        machine_tier12_hit=machine_hit,
        model=ctx.model,
        base_url=ctx.base_url,
        temperature=ctx.temperature,
    )
    r_llm = max(0, min(32, int(ctx.semantic.get("r_llm_optional") or 0)))
    ctx.component_scores["r_llm_optional"] = r_llm


def step_fuse_risk_and_ueba(ctx: DefensePipelineContext) -> None:
    semantic = ctx.semantic
    tier_h = int(semantic.get("tier_h") or 0)
    tier_i = int(semantic.get("tier_i") or 0)
    r_llm_optional = int(ctx.component_scores.get("r_llm_optional") or 0)

    fusion = fuse_risk_score_weighted(
        r_rules=ctx.r_rules,
        r_threat_intel=ctx.r_threat_intel,
        r_tls=ctx.r_tls,
        r_toxic_fused=ctx.r_toxic_fused,
        r_llm_optional=r_llm_optional,
        tier_h=tier_h,
        tier_i=tier_i,
    )
    r_final = fusion.r_fused
    machine = fusion.machine
    cs = ctx.component_scores
    cs["r_machine_base"] = machine.r_machine_base
    cs["r_machine_support_bonus"] = machine.r_machine_support_bonus
    cs["r_machine_final"] = machine.r_machine_final
    cs["r_machine_max"] = machine.r_machine_final
    cs["r_llm_100"] = fusion.r_llm_100

    verdict_pre = verdict_from_score(r_final)
    dom = dominant_source({k: v for k, v in cs.items() if k != "r_llm_optional"})
    ur = compute_user_risk(
        text=ctx.text,
        source=ctx.source,
        llm_verdict=verdict_pre,
        risk_total_fused=r_final,
    )
    cs["r_ueba"] = int(ur.s_user_0_100)
    safety_summary_raw = str(semantic.get("safety_summary") or "").strip()
    semantic_labels = list(semantic.get("labels") or [])
    risk_score, adjusted, delta_effective, semantic_floor, ueba_guard = finalize_display_risk_score(
        r_final,
        delta_user=int(ur.delta_user),
        r_rules=ctx.r_rules,
        r_threat_intel=ctx.r_threat_intel,
        r_llm_optional=r_llm_optional,
        safety_summary=safety_summary_raw,
        semantic_labels=semantic_labels,
    )
    cs["delta_user"] = int(ur.delta_user)
    cs["delta_user_effective"] = delta_effective
    cs["adjusted"] = adjusted
    cs["semantic_floor"] = semantic_floor
    cs["risk_score"] = risk_score
    verdict = verdict_from_score(risk_score)

    evidence: list[dict[str, Any]] = []
    evidence.extend(rules_hits_to_dict(ctx.rules_res.hits))
    evidence.extend(ctx.ti_evidence)
    evidence.extend(ctx.tls_evidence)
    if ctx.toxic_meta.get("s_tox", 0):
        evidence.append({"source": "toxic_db", **ctx.toxic_meta})
    for q in semantic.get("quotes") or []:
        if isinstance(q, dict):
            evidence.append({"source": "semantic_llm", **q})

    reason_highlights: list[str] = []
    if ctx.r_rules >= 25:
        reason_highlights.append(f"硬規則命中（{ctx.r_rules} 分）")
    if ctx.r_threat_intel >= 15:
        reason_highlights.append(f"URL 威脅情資（{ctx.r_threat_intel} 分）")
    if ctx.r_tls:
        reason_highlights.append(f"TLS 異常（{ctx.r_tls} 分）")
    if ctx.r_toxic_fused >= 40:
        reason_highlights.append(f"毒樣相似（{ctx.r_toxic_fused} 分）")
    if r_llm_optional:
        reason_highlights.append(f"語意框架/語言品質（{r_llm_optional} 分）")
    if len(reason_highlights) < 3 and summary_indicates_scam(safety_summary_raw) and ctx.r_rules < 25:
        if tier_h:
            reason_highlights.append(f"台灣詐騙框架語意（H {tier_h}）")
        if tier_i and len(reason_highlights) < 3:
            reason_highlights.append(f"語言品質異常（I {tier_i}）")

    track_a = {
        "tier_scores": {"H": tier_h, "I": tier_i},
        "matched_rules": rules_hits_to_dict(ctx.rules_res.hits),
        "missing_evidence": list(ctx.missing_evidence),
    }

    report: dict[str, Any] = {
        "risk_score": risk_score,
        "risk_score_total": risk_score,
        "r_final_machine": machine.r_machine_final,
        "verdict": verdict,
        "gate_tier": verdict if verdict in ("allow", "warn", "block") else "quarantine",
        "dominant_source": dom,
        "component_scores": cs,
        "evidence": evidence,
        "reason_highlights": reason_highlights[:6],
        "track_a": track_a,
        "safety_summary": "",
        "archive_note": (str(semantic.get("explanation") or "")[:80] or f"風險 {risk_score}/100"),
        "labels": semantic_labels,
        "risk_fusion": {
            "mode": "machine_support_bonus_weighted",
            "llm_weight": dai_risk_llm_weight(),
            "machine_weight": round(1.0 - dai_risk_llm_weight(), 4),
            "r_machine_base": machine.r_machine_base,
            "r_machine_support_bonus": machine.r_machine_support_bonus,
            "r_machine_final": machine.r_machine_final,
            "r_llm_100": fusion.r_llm_100,
            "r_fused_pre_ueba": r_final,
            "r_final": r_final,
            "risk_total": risk_score,
            "hard_guard_applied": fusion.hard_guard_applied,
            "ueba_guard_applied": ueba_guard,
            "semantic_floor_applied": semantic_floor > 0 and risk_score >= semantic_floor,
            "toxic": ctx.toxic_meta,
        },
        "semantic": semantic,
        "analysis_payload": ctx.payload,
        "pipeline_phases": list(SMS_REVIEW_DAG),
        "recommended_cai_action": recommended_cai_action(verdict, risk_score, r_rules=ctx.r_rules),
        "dai_skill_trace": list(ctx.skill_trace),
    }
    apply_ueba_to_report(report, text=ctx.text, source=ctx.source)
    report["risk_score"] = risk_score
    report["risk_score_total_user_fused"] = int(report.get("risk_score_total_user_fused") or risk_score)
    if max(ctx.r_rules, ctx.r_threat_intel) >= 85:
        report["risk_score_total_user_fused"] = max(
            int(report["risk_score_total_user_fused"]),
            max(ctx.r_rules, ctx.r_threat_intel),
            r_final,
        )
        report["risk_score"] = report["risk_score_total_user_fused"]
    enrich_report_display_fields(report, text=ctx.text, source=ctx.source)
    ctx.report = report


STEP_HANDLERS = {
    "build_analysis_payload": step_build_analysis_payload,
    "score_rules": step_score_rules,
    "score_threat_intel": step_score_threat_intel,
    "score_tls": step_score_tls,
    "score_toxic": step_score_toxic,
    "semantic_supplement": step_semantic_supplement,
    "fuse_risk_and_ueba": step_fuse_risk_and_ueba,
}
