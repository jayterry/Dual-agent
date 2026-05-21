"""R-LLM 35% / 機器 65% 加權融合（融合 v2）。"""

from __future__ import annotations

from dual_agent.dai.risk_analysis.verdict import fuse_risk_score_weighted, scale_llm_score_to_100


def test_scale_llm_32_to_100() -> None:
    assert scale_llm_score_to_100(32) == 100
    assert scale_llm_score_to_100(2) == 6


def test_fusion_formula_65_35() -> None:
    fusion = fuse_risk_score_weighted(
        r_rules=25,
        r_threat_intel=0,
        r_tls=0,
        r_toxic_fused=0,
        r_llm_optional=16,
        tier_h=0,
        tier_i=0,
        llm_weight=0.35,
    )
    assert fusion.machine.r_machine_final == 25
    assert fusion.r_llm_100 == 50
    assert fusion.r_fused == round(0.65 * 25 + 0.35 * 50)


def test_env_override_llm_weight() -> None:
    heavy = fuse_risk_score_weighted(
        r_rules=0,
        r_threat_intel=0,
        r_tls=0,
        r_toxic_fused=0,
        r_llm_optional=32,
        llm_weight=0.8,
    )
    light = fuse_risk_score_weighted(
        r_rules=0,
        r_threat_intel=0,
        r_tls=0,
        r_toxic_fused=0,
        r_llm_optional=32,
        llm_weight=0.2,
    )
    assert heavy.r_fused > light.r_fused
