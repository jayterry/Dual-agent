"""CAI / DAI 技能目錄拆分。"""

from __future__ import annotations

from dual_agent.skills_registry import (
    SKILLS_DAI,
    get_tool_catalog_cai,
    get_tool_catalog_dai,
)


def test_cai_catalog_excludes_dai_pipeline_skills() -> None:
    cai_names = {x["name"] for x in get_tool_catalog_cai()}
    assert "call_dai" in cai_names
    assert "score_rules" not in cai_names
    assert "fuse_risk_and_ueba" not in cai_names


def test_dai_catalog_has_pipeline_skills() -> None:
    dai_names = {x["name"] for x in get_tool_catalog_dai()}
    assert "dual_path_analyze" in dai_names
    assert "fuse_risk_and_ueba" in dai_names  # legacy skill 仍可載入
    assert "build_analysis_payload" in dai_names
    assert "call_dai" not in dai_names


def test_skills_dai_map() -> None:
    assert "score_rules" in SKILLS_DAI
    assert SKILLS_DAI["score_rules"].agent == "dai"
