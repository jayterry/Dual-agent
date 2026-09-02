"""ML 特徵抽取與標註讀寫測試。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from dual_agent.dai.risk_analysis.ml.feature_extractor import extract_features
from dual_agent.dai.risk_analysis.ml.feature_spec import FEATURE_SPEC_VERSION, all_feature_names
from dual_agent.dai.risk_analysis.ml.labels import LabelRecord, load_labels_jsonl, write_labels_jsonl
from dual_agent.dai.risk_analysis.ml.pipeline_replay import replay_feature_context
from dual_agent.dai.risk_analysis.rules import score_r_rules


def test_feature_names_stable() -> None:
    names = all_feature_names()
    assert FEATURE_SPEC_VERSION == "risk_features_v1"
    assert len(names) == len(set(names))
    assert "hit_otp" in names
    assert "r_rules" in names


def test_extract_features_password_hit() -> None:
    text = "請立即驗證您的網路銀行密碼並回傳"
    rules = score_r_rules(text)
    fv = extract_features(
        text=text,
        component_scores={
            "r_rules": rules.score,
            "r_threat_intel": 0,
            "r_tls": 0,
            "r_toxic_fused": 0,
            "tier_h": 0,
            "tier_i": 0,
            "r_llm_optional": 0,
        },
        rules_hits=[{"rule_id": h.rule_id, "points": h.points} for h in rules.hits],
    )
    d = fv.to_dict()
    assert d["hit_password_credentials"] == 1.0
    assert d["r_rules"] == 90.0
    assert len(fv.values) == len(all_feature_names())


def test_replay_without_semantic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prev = os.environ.get("DAI_SEMANTIC_LLM")
        os.environ["DAI_SEMANTIC_LLM"] = "0"
        try:
            text = "請立即驗證您的網路銀行密碼並回傳"
            pipe = replay_feature_context(text, with_semantic=False)
            assert pipe.r_rules >= 80, f"r_rules={pipe.r_rules}"
            assert int(pipe.component_scores.get("r_llm_optional") or 0) == 0
        finally:
            if prev is None:
                os.environ.pop("DAI_SEMANTIC_LLM", None)
            else:
                os.environ["DAI_SEMANTIC_LLM"] = prev


def test_labels_jsonl_roundtrip() -> None:
    rec = LabelRecord(
        id="t1",
        text="測試",
        label="benign",
        split="train",
    )
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "labels.jsonl"
        write_labels_jsonl(p, [rec])
        loaded = load_labels_jsonl(p)
        assert len(loaded) == 1
        assert loaded[0].text == "測試"
        assert loaded[0].label == "benign"
