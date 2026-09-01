"""已訓練的 Context Scorer（讀 context_model.joblib）。"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from dual_agent.dai.fraud_dual.gnn.graph import ContextGraph
from dual_agent.dai.fraud_dual.gnn.rules import ContextPrediction
from dual_agent.dai.fraud_dual.gnn.train_context import DEFAULT_CONTEXT_MODEL, signals_to_context_vector


class LearnedContextScorer:
    def __init__(self, model_path: Path | None = None):
        path = Path(model_path or DEFAULT_CONTEXT_MODEL)
        if not path.exists():
            raise FileNotFoundError(
                f"Context model not found: {path}. Run: python -m scripts.train_context"
            )
        self.bundle = joblib.load(path)
        self.model_path = path

    def predict_context(self, graph_payload: dict) -> float:
        return self.predict(graph_payload).context_score

    def predict(self, graph_or_payload: ContextGraph | dict) -> ContextPrediction:
        if isinstance(graph_or_payload, ContextGraph):
            sig = graph_or_payload.extract_signals()
        else:
            sig = graph_or_payload.get("signals") or graph_or_payload
        x = signals_to_context_vector(sig, self.bundle["encoder"])
        score = float(np.clip(self.bundle["model"].predict(x)[0], 0.0, 1.0))
        return ContextPrediction(
            context_score=round(score, 4),
            factors=["learned_context_model"],
            backend=str(self.bundle.get("version", "learned")),
        )
