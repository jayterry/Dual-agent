"""Path A — GNN / Context Graph。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from dual_agent.dai.fraud_dual.gnn.graph import ContextGraph, build_context_graph
from dual_agent.dai.fraud_dual.gnn.hetero import HeteroGNNScorer
from dual_agent.dai.fraud_dual.gnn.hetero_model import HeteroContextNet  # noqa: F401 — re-export surface
from dual_agent.dai.fraud_dual.gnn.learned import LearnedContextScorer
from dual_agent.dai.fraud_dual.gnn.rules import ContextPrediction, RuleContextScorer
from dual_agent.dai.fraud_dual.gnn.train_context import DEFAULT_CONTEXT_MODEL
from dual_agent.dai.fraud_dual.shared.schemas import GraphWriteback, ResultA, SharedFeatures, ThreatResult

__all__ = [
    "ContextScorer",
    "ContextGraph",
    "ContextPrediction",
    "RuleContextScorer",
    "LearnedContextScorer",
    "HeteroGNNScorer",
    "build_context_graph",
    "get_context_scorer",
    "score_context",
    "assemble_result_a",
]


class ContextScorer(Protocol):
    """Context 推論介面；只產出 context_score，不改寫 threat／scam_type。"""

    def predict_context(self, graph_payload: dict) -> float: ...


BackendName = Literal["rules", "learned", "hetero", "auto"]


def get_context_scorer(backend: BackendName = "auto") -> ContextScorer:
    if backend == "auto":
        # Prefer HistGBDT（穩）；Hetero 需 torch-geometric，失敗則降級
        if Path(DEFAULT_CONTEXT_MODEL).exists():
            return LearnedContextScorer()
        try:
            from dual_agent.dai.fraud_dual.gnn.hetero_model import DEFAULT_HETERO_PATH

            if Path(DEFAULT_HETERO_PATH).exists():
                return HeteroGNNScorer()
        except Exception:
            pass
        return RuleContextScorer()
    if backend == "rules":
        return RuleContextScorer()
    if backend == "learned":
        return LearnedContextScorer()
    if backend == "hetero":
        return HeteroGNNScorer()
    raise ValueError(f"Unknown context backend: {backend}")


def score_context(
    shared: SharedFeatures,
    writeback: GraphWriteback,
    *,
    backend: BackendName = "auto",
) -> tuple[ContextGraph, ContextPrediction]:
    graph = build_context_graph(shared, writeback)
    scorer = get_context_scorer(backend)
    payload = graph.to_payload()
    payload["signals"]["text"] = shared.text
    if hasattr(scorer, "predict"):
        pred = scorer.predict(payload)  # type: ignore[attr-defined]
    else:
        score = scorer.predict_context(payload)
        pred = ContextPrediction(context_score=score, backend=str(backend))
    return graph, pred


def assemble_result_a(
    threat: ThreatResult,
    context_score: float,
) -> ResultA:
    """組裝 Result_A；禁止對 threat／context 做數值融合。"""
    return ResultA(
        threat_score=threat.threat_score,
        threat_missing=threat.threat_missing,
        scam_type=threat.scam_type,
        intent_confidence=threat.intent_confidence,
        context_score=round(max(0.0, min(1.0, float(context_score))), 4),
    )
