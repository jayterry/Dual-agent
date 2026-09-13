"""HeteroGNN Scorer（載入 context_hetero.pt）。"""

from __future__ import annotations

from pathlib import Path

import torch

from dual_agent.dai.fraud_dual.gnn.graph import ContextGraph
from dual_agent.dai.fraud_dual.gnn.hetero_model import HeteroContextNet, sample_to_hetero
from dual_agent.dai.fraud_dual.paths import resolve_hetero_model_path
from dual_agent.dai.fraud_dual.gnn.rules import ContextPrediction
from dual_agent.dai.fraud_dual.ml.dataset import ContextSample


class HeteroGNNScorer:
    def __init__(self, model_path: Path | str | None = None):
        resolved = Path(model_path) if model_path else resolve_hetero_model_path()
        if resolved is None or not resolved.exists():
            raise FileNotFoundError(
                f"HeteroGNN not found: {model_path or 'ranking_full / context_hetero.pt'}. "
                "Run: python -m scripts.train_hetero"
            )
        path = resolved
        blob = torch.load(path, map_location="cpu", weights_only=False)
        self.model = HeteroContextNet(blob["in_dims"], hidden=blob.get("hidden", 64))
        self.model.load_state_dict(blob["state_dict"])
        self.model.eval()
        self.version = blob.get("version", "hetero")
        self.model_path = path

    def predict_context(self, graph_payload: dict) -> float:
        return self.predict_from_signals(graph_payload.get("signals") or graph_payload).context_score

    def predict(self, graph_or_payload: ContextGraph | dict) -> ContextPrediction:
        if isinstance(graph_or_payload, ContextGraph):
            sig = graph_or_payload.extract_signals()
        else:
            sig = graph_or_payload.get("signals") or graph_or_payload
        return self.predict_from_signals(sig)

    def predict_from_signals(self, sig: dict) -> ContextPrediction:
        # 由訊號拼最小 ContextSample（text 用佔位；話術已在圖 message 特徵時再抽）
        # 訓練／推論對齊：需要 text 才能抽 rhetoric/payload → 放進 signals 備援
        text = str(sig.get("text") or "")
        sample = ContextSample(
            text=text,
            scam_type=str(sig.get("scam_type") or "Unknown"),
            threat_score=float(sig.get("threat_score") or 0.0),
            age_band=str(sig.get("age_band") or "25-39"),
            occupation=str(sig.get("occupation") or "other"),
            relation_type=str(sig.get("relation_type") or "Unknown"),
            channel=str(sig.get("channel") or "LINE"),
            primary_apps=tuple(sig.get("primary_apps") or ["LINE"]),
            invest_exp=sig.get("invest_exp"),
            persona_role="",
            context_score=0.0,
            channel_is_familiar=int(sig.get("channel_is_familiar") or 0),
        )
        # 若無 text，用 signals 內話術／payload 數值覆蓋 message/payload（簡化：仍走 extract，回空）
        data = sample_to_hetero(sample)
        with torch.no_grad():
            score = float(self.model(data.x_dict, data.edge_index_dict).numpy()[0])
        score = max(0.0, min(1.0, score))
        return ContextPrediction(
            context_score=round(score, 4),
            factors=["hetero_gnn"],
            backend=self.version,
        )
