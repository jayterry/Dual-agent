"""ml_lr 融合：硬擋、p_fraud、legacy 預設。"""

from __future__ import annotations

import os
from pathlib import Path

from dual_agent.config import dai_risk_fusion_mode
from dual_agent.dai.risk_analysis.ml.infer import clear_model_cache, fuse_risk_score_ml
from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.rules import rules_hits_to_dict, score_r_rules
from dual_agent.dai.schemas import DAIRequest

_ROOT = Path(__file__).resolve().parents[1]
_MODEL = _ROOT / "data" / "risk_models" / "lr_bank_v0_gd" / "model.pkl"


def test_default_fusion_mode_legacy() -> None:
    old = os.environ.pop("DAI_RISK_FUSION_MODE", None)
    try:
        assert dai_risk_fusion_mode() == "legacy"
    finally:
        if old is not None:
            os.environ["DAI_RISK_FUSION_MODE"] = old


def test_ml_hard_guard_password() -> None:
    assert _MODEL.is_file()
    clear_model_cache()
    text = "請立即驗證您的網路銀行密碼並回傳"
    rules = score_r_rules(text)
    hits = rules_hits_to_dict(rules.hits)
    ml = fuse_risk_score_ml(
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
        rules_hits=hits,
        model_path=str(_MODEL),
        mode="ml_lr",
    )
    assert rules.score >= 85
    assert ml.fusion.r_fused >= 85
    assert ml.fusion.hard_guard_applied or ml.fusion.r_fused >= rules.score
    assert 0.0 <= ml.p_fraud <= 1.0


def test_pipeline_dual_path_otp() -> None:
    assert _MODEL.is_file()
    prev_pb = os.environ.get("DAI_DUAL_PATH_B")
    prev_nr = os.environ.get("DAI_DUAL_NARRATOR")
    os.environ["DAI_DUAL_PATH_B"] = "0"
    os.environ["DAI_DUAL_NARRATOR"] = "0"
    try:
        report = run_risk_analysis(
            DAIRequest(
                user_text="【玉山銀行】帳戶異常，請回傳動態密碼 123456 完成驗證",
                artifact="【玉山銀行】帳戶異常，請回傳動態密碼 123456 完成驗證",
                sms_review=True,
                source="test",
            ),
        )
        assert report.get("engine") == "fraud_dual"
        assert report.get("path_a")
        assert int(report.get("risk_score") or 0) >= 55
        assert str(report.get("verdict")) in ("warn", "block")
    finally:
        if prev_pb is None:
            os.environ.pop("DAI_DUAL_PATH_B", None)
        else:
            os.environ["DAI_DUAL_PATH_B"] = prev_pb
        if prev_nr is None:
            os.environ.pop("DAI_DUAL_NARRATOR", None)
        else:
            os.environ["DAI_DUAL_NARRATOR"] = prev_nr


def test_pipeline_dual_path_benign_has_path_a() -> None:
    prev_pb = os.environ.get("DAI_DUAL_PATH_B")
    prev_nr = os.environ.get("DAI_DUAL_NARRATOR")
    os.environ["DAI_DUAL_PATH_B"] = "0"
    os.environ["DAI_DUAL_NARRATOR"] = "0"
    try:
        report = run_risk_analysis(
            DAIRequest(
                user_text="【玉山銀行】您有一筆 NT$500 入帳，如有疑問請洽官方客服。",
                artifact="【玉山銀行】您有一筆 NT$500 入帳，如有疑問請洽官方客服。",
                sms_review=True,
                source="test",
            ),
        )
        assert report.get("engine") == "fraud_dual"
        assert isinstance(report.get("path_a"), dict)
    finally:
        if prev_pb is None:
            os.environ.pop("DAI_DUAL_PATH_B", None)
        else:
            os.environ["DAI_DUAL_PATH_B"] = prev_pb
        if prev_nr is None:
            os.environ.pop("DAI_DUAL_NARRATOR", None)
        else:
            os.environ["DAI_DUAL_NARRATOR"] = prev_nr
