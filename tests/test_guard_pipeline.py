"""Guard 管線：融合數學與 mock Guard（不依賴 Ollama）。"""

from __future__ import annotations

from unittest.mock import patch

from dual_agent.dai.defense_llm import GuardExtracted, GuardReport, GuardSignal, _normalize_verdict
from dual_agent.dai.guard_pipeline import run_guard_analysis_pipeline
from dual_agent.dai.schemas import DAIRequest
from dual_agent.dai.toxic_fusion import fuse_risk


def test_fuse_risk_default_weights() -> None:
    f = fuse_risk(r_llm_0_100=80, s_tox_0_100=40)
    assert f.r_llm_0_100 == 80
    assert f.s_tox_0_100 == 40
    assert f.risk_total_0_100 == int(round(0.75 * 80 + 0.25 * 40))


def test_normalize_verdict() -> None:
    assert _normalize_verdict("BLOCK") == "block"
    assert _normalize_verdict("nope") == "quarantine"


def _minimal_guard_report() -> GuardReport:
    return GuardReport(
        verdict="allow",
        risk_score_total=60,
        injection_score=30,
        scam_score=40,
        labels=["test"],
        signals=[GuardSignal(type="t", severity="low", evidence="e")],
        extracted=GuardExtracted(),
        sanitized_memory="摘要",
        archive_note="結論",
        model_name="mock",
    )


@patch("dual_agent.dai.guard_pipeline.invoke_defense_guard_scan")
@patch("dual_agent.dai.guard_pipeline.match_toxic")
def test_run_guard_analysis_pipeline_order(mock_toxic: object, mock_guard: object) -> None:
    mock_guard.return_value = _minimal_guard_report()
    from dual_agent.dai.toxic_fusion import ToxicMatch

    mock_toxic.return_value = ToxicMatch(0.9, "t1", 50, 128, 3)

    with patch.dict(
        "os.environ",
        {
            "TOXIC_DB_PATH": "/no/such/file.json",
            "TOXIC_CHROMA_PERSIST_DIR": "",
            "TOXIC_CHROMA_COLLECTION": "",
        },
        clear=False,
    ):
        out = run_guard_analysis_pipeline(DAIRequest(user_text="hello", artifact=""))

    mock_guard.assert_called_once()
    assert "risk_fusion" in out
    assert out["gate_tier"] in ("allow", "warn", "block")
    assert out["pipeline_phases"][0] == "defense_guard_scan"
