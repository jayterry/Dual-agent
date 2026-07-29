"""
從 DAI 風險 DAG 中間結果組固定長度 ML 特徵向量（FEATURE_SPEC_VERSION）。

特徵群：
- 規則 one-hot：hit_<rule_id>
- 連續分項：r_rules / r_threat_intel / r_tls / r_toxic_fused / tier_h / tier_i / r_llm_optional
- 機器衍生：r_machine_*、r_llm_100
- LLM 標籤 one-hot：lbl_*
- 結構：text_len、url_count、phone_count、amount_count…
- UEBA／來源頻道

呼叫端未傳 phones／amounts／urls 時，會以輕量 regex 自正文回填，避免匯出全 0。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from dual_agent.dai.risk_analysis.ml.feature_spec import (
    CONTINUOUS_SCORE_KEYS,
    RULE_IDS,
    SEMANTIC_LABEL_KEYS,
    SOURCE_CHANNEL_KEYS,
    all_feature_names,
)
from dual_agent.dai.risk_analysis.rules import rules_hits_to_dict
from dual_agent.dai.risk_analysis.verdict import compute_r_machine, scale_llm_score_to_100
from dual_agent.dai.user_db import compute_user_risk

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}"
    r"|(?:\+?886[-\s]?)?0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{3,4}"
)
_AMOUNT_RE = re.compile(
    r"(?:NT\$|USD\$|\$|美金|新台幣|元)\s*[\d,]+(?:\.\d+)?|[\d,]+\s*(?:元|塊)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RiskFeatureVector:
    names: tuple[str, ...]
    values: tuple[float, ...]

    def to_dict(self) -> dict[str, float]:
        return dict(zip(self.names, self.values, strict=True))

    def to_list(self) -> list[float]:
        return list(self.values)


def _norm_label(raw: str) -> str:
    return str(raw or "").strip().lower().replace("-", "_")


def _vendor_count_max(url_threat_hits: list[dict[str, Any]]) -> int:
    best = 0
    for row in url_threat_hits or []:
        if not isinstance(row, dict):
            continue
        hits = row.get("hits") if isinstance(row.get("hits"), dict) else {}
        vc = int(row.get("vendor_count") or 0)
        if vc <= 0 and hits:
            vc = sum(1 for v in hits.values() if v is True)
        best = max(best, vc)
    return best


def _source_channel_flags(source: str) -> dict[str, float]:
    s = (source or "").strip().lower()
    flags = {k: 0.0 for k in SOURCE_CHANNEL_KEYS}
    if not s or s in ("unknown", "desktop"):
        flags["src_desktop" if s == "desktop" else "src_unknown"] = 1.0
        return flags
    if "sms" in s:
        flags["src_sms"] = 1.0
    elif "notif" in s:
        flags["src_notification"] = 1.0
    else:
        flags["src_unknown"] = 1.0
    return flags


def _fallback_urls(text: str) -> list[str]:
    return [m.group(0).rstrip(".,);]") for m in _URL_RE.finditer(text or "")]


def _fallback_phones(text: str) -> list[str]:
    return [m.group(0) for m in _PHONE_RE.finditer(text or "")]


def _fallback_amounts(text: str) -> list[str]:
    return [m.group(0) for m in _AMOUNT_RE.finditer(text or "")]


def extract_features(
    *,
    text: str,
    component_scores: dict[str, int],
    rules_hits: list[dict[str, Any]],
    semantic: dict[str, Any] | None = None,
    toxic_meta: dict[str, Any] | None = None,
    url_threat_hits: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    source: str = "desktop",
    phones: list[str] | None = None,
    amounts: list[str] | None = None,
    urls: list[str] | None = None,
) -> RiskFeatureVector:
    sem = semantic or {}
    cs = {k: int(component_scores.get(k) or 0) for k in CONTINUOUS_SCORE_KEYS}
    toxic = toxic_meta or {}
    url_hits = list(url_threat_hits or [])

    hit_ids = {
        str(h.get("rule_id") or "")
        for h in (rules_hits or [])
        if isinstance(h, dict) and h.get("rule_id")
    }

    machine = compute_r_machine(
        r_rules=cs["r_rules"],
        r_threat_intel=cs["r_threat_intel"],
        r_tls=cs["r_tls"],
        r_toxic_fused=cs["r_toxic_fused"],
    )
    r_llm_100 = scale_llm_score_to_100(
        cs["r_llm_optional"],
        tier_h=cs["tier_h"],
        tier_i=cs["tier_i"],
    )

    label_set = {_norm_label(x) for x in (sem.get("labels") or []) if _norm_label(x)}

    t = (text or "").strip()
    url_list = list(urls) if urls else _fallback_urls(t)
    phone_list = list(phones) if phones else _fallback_phones(t)
    amount_list = list(amounts) if amounts else _fallback_amounts(t)

    ur = compute_user_risk(
        text=t,
        source=source,
        llm_verdict="allow",
        risk_total_fused=0,
    )
    domain_unknown = 0.0
    for row in ur.trusted_urls or []:
        if isinstance(row, dict) and not row.get("trusted") and not row.get("blocked"):
            domain_unknown = 1.0
            break

    src_flags = _source_channel_flags(source)

    values_map: dict[str, float] = {}

    for rid in RULE_IDS:
        values_map[f"hit_{rid}"] = 1.0 if rid in hit_ids else 0.0

    for k in CONTINUOUS_SCORE_KEYS:
        values_map[k] = float(cs[k])

    values_map["r_machine_base"] = float(machine.r_machine_base)
    values_map["r_machine_support_bonus"] = float(machine.r_machine_support_bonus)
    values_map["r_machine_final"] = float(machine.r_machine_final)
    values_map["r_llm_100"] = float(r_llm_100)

    for lk in SEMANTIC_LABEL_KEYS:
        values_map[f"lbl_{lk}"] = 1.0 if lk in label_set else 0.0

    values_map["text_len"] = float(len(t))
    values_map["url_count"] = float(len(url_list))
    values_map["has_https"] = 1.0 if re.search(r"https?://", t, re.I) else 0.0
    values_map["phone_count"] = float(len(phone_list))
    values_map["amount_count"] = float(len(amount_list))
    values_map["toxic_max_cosine"] = float(toxic.get("max_cosine") or 0.0)
    values_map["ti_vendor_count_max"] = float(_vendor_count_max(url_hits))
    values_map["missing_evidence_count"] = float(len(missing_evidence or []))

    values_map["delta_user"] = float(ur.delta_user)
    values_map["s_user"] = float(ur.s_user_0_100)
    values_map["source_trusted"] = 1.0 if ur.trusted else 0.0
    values_map["source_blocked"] = 1.0 if ur.blocked else 0.0
    values_map["domain_unknown"] = domain_unknown

    for k, v in src_flags.items():
        values_map[k] = v

    names = all_feature_names()
    return RiskFeatureVector(names=names, values=tuple(values_map[n] for n in names))


def features_from_pipeline_context(pipe: Any) -> RiskFeatureVector:
    """自 DefensePipelineContext 抽取特徵（離線重播用）。"""
    ents = (pipe.payload or {}).get("entities") or {}
    hits = rules_hits_to_dict(pipe.rules_res.hits) if pipe.rules_res is not None else []
    return extract_features(
        text=pipe.text,
        component_scores=dict(pipe.component_scores or {}),
        rules_hits=hits,
        semantic=dict(pipe.semantic or {}),
        toxic_meta=dict(pipe.toxic_meta or {}),
        url_threat_hits=list(pipe.url_threat_hits or []),
        missing_evidence=list(pipe.missing_evidence or []),
        source=str(pipe.source or "desktop"),
        phones=list(ents.get("phones") or []),
        amounts=list(ents.get("amounts") or []),
        urls=list(pipe.urls_from_text or []),
    )


def features_from_pipeline_context(pipe: Any) -> RiskFeatureVector:
    """自 DefensePipelineContext 抽取特徵（離線重播用）。"""
    ents = (pipe.payload or {}).get("entities") or {}
    hits = rules_hits_to_dict(pipe.rules_res.hits) if pipe.rules_res is not None else []
    return extract_features(
        text=pipe.text,
        component_scores=dict(pipe.component_scores or {}),
        rules_hits=hits,
        semantic=dict(pipe.semantic or {}),
        toxic_meta=dict(pipe.toxic_meta or {}),
        url_threat_hits=list(pipe.url_threat_hits or []),
        missing_evidence=list(pipe.missing_evidence or []),
        source=str(pipe.source or "desktop"),
        phones=list(ents.get("phones") or []),
        amounts=list(ents.get("amounts") or []),
        urls=list(pipe.urls_from_text or []),
    )
