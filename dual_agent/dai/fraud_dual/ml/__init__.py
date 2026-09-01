"""Path A — ML 威脅模組。"""

from __future__ import annotations

from dual_agent.dai.fraud_dual.ml.infer import ThreatPredictor, build_graph_writeback, get_predictor
from dual_agent.dai.fraud_dual.ml.train import train_and_save
from dual_agent.dai.fraud_dual.shared.schemas import GraphWriteback, SharedFeatures, ThreatResult

__all__ = [
    "ThreatPredictor",
    "ThreatResult",
    "GraphWriteback",
    "build_graph_writeback",
    "get_predictor",
    "train_and_save",
    "predict_threat",
]


def predict_threat(shared: SharedFeatures) -> tuple[ThreatResult, GraphWriteback]:
    pred = get_predictor()
    threat = pred.predict(shared)
    wb = build_graph_writeback(shared, threat)
    return threat, wb
