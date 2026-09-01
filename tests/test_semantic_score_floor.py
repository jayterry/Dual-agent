"""semantic_labels 顯示分下限（融合 v2 單元）+ 雙路身分恐嚇。"""

from __future__ import annotations

from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.risk_analysis.rules import score_r_rules
from dual_agent.dai.risk_analysis.verdict import finalize_display_risk_score, summary_indicates_scam
from dual_agent.dai.schemas import DAIRequest

_IDENTITY_SMS = (
    "【重要通知】您尚未辦理簽署實名認證，帳戶將於今日凍結。"
    "請立即點擊連結完成認證，否則將停權。此為政府補助專案通知。"
)


def test_identity_rules_hit() -> None:
    res = score_r_rules(_IDENTITY_SMS)
    assert res.score >= 25
    assert any(h.rule_id == "identity_scam_framework" for h in res.hits)


def test_summary_indicates_scam() -> None:
    assert summary_indicates_scam("這則訊息可能涉及詐騙行為，建議提高警覺。")
    assert not summary_indicates_scam("一般帳單通知，請至官網查詢。")


def test_finalize_floor_from_phishing_label() -> None:
    score, _, _, floor, _ = finalize_display_risk_score(
        2,
        delta_user=2,
        r_rules=0,
        r_threat_intel=0,
        safety_summary="可能涉及詐騙行為，請勿輕信。",
        semantic_labels=["phishing"],
    )
    assert floor >= 60
    assert score >= 60


def test_pipeline_identity_dual_path() -> None:
    import os

    prev_pb = os.environ.get("DAI_DUAL_PATH_B")
    prev_nr = os.environ.get("DAI_DUAL_NARRATOR")
    os.environ["DAI_DUAL_PATH_B"] = "0"
    os.environ["DAI_DUAL_NARRATOR"] = "0"
    try:
        req = DAIRequest(user_text="送審", artifact=_IDENTITY_SMS, sms_review=True)
        report = run_risk_analysis(req)
        assert report.get("engine") == "fraud_dual"
        assert int(report["risk_score"]) >= 15
        assert report.get("path_a")
        assert report["verdict"] in ("allow", "warn", "block")
    finally:
        if prev_pb is None:
            os.environ.pop("DAI_DUAL_PATH_B", None)
        else:
            os.environ["DAI_DUAL_PATH_B"] = prev_pb
        if prev_nr is None:
            os.environ.pop("DAI_DUAL_NARRATOR", None)
        else:
            os.environ["DAI_DUAL_NARRATOR"] = prev_nr
