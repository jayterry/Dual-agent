"""融合 v2：machine 支援加成、LLM 35%、UEBA、semantic_labels 下限。"""

from __future__ import annotations

import os

from dual_agent.config import dai_risk_llm_weight
from dual_agent.dai.risk_analysis.verdict import (
    clamp_delta_user_effective,
    compute_r_machine,
    finalize_display_risk_score,
    fuse_risk_score_weighted,
    semantic_floor_from_labels,
    verdict_from_score,
)


def test_machine_support_bonus_stacked() -> None:
    m = compute_r_machine(r_rules=60, r_threat_intel=50, r_tls=40, r_toxic_fused=0)
    assert m.r_machine_base == 60
    assert m.r_machine_support_bonus == round(0.15 * 50 + 0.10 * 40)  # 12
    assert m.r_machine_final == 72


def test_fusion_rules_90_hard_guard() -> None:
    fusion = fuse_risk_score_weighted(
        r_rules=90,
        r_threat_intel=0,
        r_tls=0,
        r_toxic_fused=0,
        r_llm_optional=0,
        llm_weight=0.35,
    )
    assert fusion.r_fused >= 90
    assert fusion.hard_guard_applied


def test_ueba_delta_asymmetric() -> None:
    assert clamp_delta_user_effective(-15) == -8
    assert clamp_delta_user_effective(20) == 15
    assert clamp_delta_user_effective(0) == 0


def test_semantic_floor_labels() -> None:
    assert semantic_floor_from_labels(["phishing"]) >= 60
    assert semantic_floor_from_labels(["financial_extortion"]) >= 85


def test_verdict_only_from_risk_score() -> None:
    assert verdict_from_score(85) == "block"
    assert verdict_from_score(70) == "warn"
    assert verdict_from_score(69) == "allow"


def test_finalize_labels_not_summary() -> None:
    score, _, _, floor, _ = finalize_display_risk_score(
        4,
        delta_user=0,
        r_rules=0,
        r_threat_intel=0,
        safety_summary="可能涉及詐騙行為",
        semantic_labels=["phishing"],
    )
    assert floor >= 60
    assert score >= 60


def test_default_llm_weight_35_env_clear() -> None:
    old = os.environ.pop("DAI_R_LLM_WEIGHT", None)
    try:
        assert dai_risk_llm_weight() == 0.35
    finally:
        if old is not None:
            os.environ["DAI_R_LLM_WEIGHT"] = old
