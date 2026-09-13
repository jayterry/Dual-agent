"""Context auto 選型：GNN 優先，HistGBDT 不得擋住。"""

from __future__ import annotations

from pathlib import Path

from dual_agent.dai.fraud_dual.gnn import get_context_scorer
from dual_agent.dai.fraud_dual.gnn.learned import LearnedContextScorer
from dual_agent.dai.fraud_dual.gnn.rules import RuleContextScorer
from dual_agent.dai.fraud_dual.paths import resolve_hetero_model_path


class _FakeHetero:
    def __init__(self, *args, **kwargs) -> None:
        self.backend = "hetero_sage_ranking_v1"

    def predict_context(self, graph_payload: dict) -> float:
        return 0.4


def test_auto_prefers_hetero_even_if_joblib_exists(monkeypatch) -> None:
    monkeypatch.setattr(
        "dual_agent.dai.fraud_dual.gnn._try_hetero",
        lambda: _FakeHetero(),
    )
    monkeypatch.setattr(
        "dual_agent.dai.fraud_dual.gnn._try_learned",
        lambda: LearnedContextScorer.__new__(LearnedContextScorer),
    )
    scorer = get_context_scorer("auto")
    assert isinstance(scorer, _FakeHetero)


def test_auto_falls_back_to_learned_when_gnn_missing(monkeypatch) -> None:
    class FakeLearned:
        def predict_context(self, graph_payload: dict) -> float:
            return 0.2

    monkeypatch.setattr("dual_agent.dai.fraud_dual.gnn._try_hetero", lambda: None)
    monkeypatch.setattr("dual_agent.dai.fraud_dual.gnn._try_learned", lambda: FakeLearned())
    scorer = get_context_scorer("auto")
    assert isinstance(scorer, FakeLearned)


def test_auto_falls_back_to_rules(monkeypatch) -> None:
    monkeypatch.setattr("dual_agent.dai.fraud_dual.gnn._try_hetero", lambda: None)
    monkeypatch.setattr("dual_agent.dai.fraud_dual.gnn._try_learned", lambda: None)
    scorer = get_context_scorer("auto")
    assert isinstance(scorer, RuleContextScorer)


def test_env_backend_rules(monkeypatch) -> None:
    monkeypatch.setenv("DAI_CONTEXT_BACKEND", "rules")
    scorer = get_context_scorer("auto")
    assert isinstance(scorer, RuleContextScorer)


def test_resolve_hetero_prefers_ranking_full(tmp_path: Path, monkeypatch) -> None:
    ranking = tmp_path / "context_hetero_ranking_full.pt"
    ranking.write_bytes(b"x")
    mse = tmp_path / "context_hetero.pt"
    mse.write_bytes(b"y")
    monkeypatch.delenv("DAI_HETERO_MODEL_PATH", raising=False)
    monkeypatch.setattr(
        "dual_agent.dai.fraud_dual.paths.HETERO_RANKING_FULL_PATH",
        ranking,
    )
    monkeypatch.setattr(
        "dual_agent.dai.fraud_dual.paths.HETERO_MODEL_PATH",
        mse,
    )
    got = resolve_hetero_model_path()
    assert got == ranking
