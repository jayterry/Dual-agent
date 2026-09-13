"""Path A — GNN / Context Graph。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal, Protocol

from dual_agent.dai.fraud_dual.gnn.graph import ContextGraph, build_context_graph
from dual_agent.dai.fraud_dual.gnn.hetero import HeteroGNNScorer
from dual_agent.dai.fraud_dual.gnn.hetero_model import HeteroContextNet  # noqa: F401 — re-export surface
from dual_agent.dai.fraud_dual.gnn.learned import LearnedContextScorer
from dual_agent.dai.fraud_dual.gnn.rules import ContextPrediction, RuleContextScorer
from dual_agent.dai.fraud_dual.gnn.train_context import DEFAULT_CONTEXT_MODEL
from dual_agent.dai.fraud_dual.paths import resolve_hetero_model_path
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
    "resolve_context_backend",
]

_LOG = logging.getLogger(__name__)


class ContextScorer(Protocol):
    """Context 推論介面；只產出 context_score，不改寫 threat／scam_type。"""

    def predict_context(self, graph_payload: dict) -> float: ...


BackendName = Literal["rules", "learned", "hetero", "auto"]


def resolve_context_backend(requested: BackendName = "auto") -> BackendName:
    if requested != "auto":
        return requested
    raw = os.environ.get("DAI_CONTEXT_BACKEND", "auto").strip().lower()
    if raw in ("auto", "hetero", "learned", "rules"):
        return raw  # type: ignore[return-value]
    return "auto"


def _try_hetero() -> ContextScorer | None:
    if resolve_hetero_model_path() is None:
        return None
    try:
        return HeteroGNNScorer()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("HeteroGNN unavailable, falling back: %s", exc)
        return None


def _try_learned() -> ContextScorer | None:
    if not Path(DEFAULT_CONTEXT_MODEL).exists():
        return None
    try:
        return LearnedContextScorer()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("HistGBDT context model unavailable, falling back: %s", exc)
        return None


def get_context_scorer(backend: BackendName = "auto") -> ContextScorer:
    """auto：GNN → HistGBDT → 規則。GBDT 檔不得擋住 GNN。"""
    chosen = resolve_context_backend(backend)
    if chosen == "auto":
        hetero = _try_hetero()
        if hetero is not None:
            return hetero
        learned = _try_learned()
        if learned is not None:
            return learned
        return RuleContextScorer()
    if chosen == "rules":
        return RuleContextScorer()
    if chosen == "learned":
        return LearnedContextScorer()
    if chosen == "hetero":
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
    *,
    backend: str = "",
    factors: list[str] | None = None,
) -> ResultA:
    """組裝 Result_A；禁止對 threat／context 做數值融合。"""
    return ResultA(
        threat_score=threat.threat_score,
        threat_missing=threat.threat_missing,
        scam_type=threat.scam_type,
        intent_confidence=threat.intent_confidence,
        context_score=round(max(0.0, min(1.0, float(context_score))), 4),
        context_backend=str(backend or ""),
        context_factors=list(factors or []),
    )
