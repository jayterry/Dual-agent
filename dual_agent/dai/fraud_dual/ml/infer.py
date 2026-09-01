"""Threat 推論與圖譜回寫。"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
from scipy import sparse

from dual_agent.dai.fraud_dual.ml.vectorize import structured_vector
from dual_agent.dai.fraud_dual.paths import THREAT_MODEL_PATH
from dual_agent.dai.fraud_dual.shared.schemas import GraphWriteback, SharedFeatures, ThreatResult

DEFAULT_MODEL_PATH = THREAT_MODEL_PATH


class ThreatPredictor:
    def __init__(self, model_path: Path | None = None):
        path = Path(model_path or DEFAULT_MODEL_PATH)
        if not path.exists():
            raise FileNotFoundError(
                f"Model not found: {path}. Run: python -m scripts.train_ml"
            )
        self.bundle = joblib.load(path)
        self.model_path = path

    def predict(self, shared: SharedFeatures) -> ThreatResult:
        tfidf = self.bundle["tfidf"]
        scaler = self.bundle["scaler"]
        label_encoder = self.bundle["label_encoder"]
        xgb = self.bundle["xgb"]
        threat_lr = self.bundle["threat_lr"]

        X_struct = scaler.transform(structured_vector(shared).reshape(1, -1))
        X_text = tfidf.transform([shared.text])
        X = sparse.hstack([sparse.csr_matrix(X_struct), X_text], format="csr")

        proba = xgb.predict_proba(X)[0]
        idx = int(np.argmax(proba))
        scam_type = str(label_encoder.inverse_transform([idx])[0])
        intent_confidence = float(proba[idx])

        threat_score = float(threat_lr.predict_proba(X)[0, 1])
        threat_missing = 0

        # Unknown + 低威脅：維持類型 Unknown
        if scam_type == "Unknown" and threat_score < 0.35:
            pass
        elif scam_type == "Unknown" and threat_score >= 0.55:
            # 高威脅但類型不確定 → 保留 Unknown，交由後續標註
            pass

        return ThreatResult(
            threat_score=round(max(0.0, min(1.0, threat_score)), 4),
            threat_missing=threat_missing,
            scam_type=scam_type,  # type: ignore[arg-type]
            intent_confidence=round(max(0.0, min(1.0, intent_confidence)), 4),
        )


def build_graph_writeback(shared: SharedFeatures, threat: ThreatResult) -> GraphWriteback:
    """依規格回寫 Message / Intent / Payload 類型清單。"""
    p = shared.payload_features
    payload_types: list[str] = []
    if p.contains_url:
        payload_types.append("URL")
    if p.contains_apk:
        payload_types.append("APP")
    if p.contains_account:
        payload_types.append("Account")
    if p.contains_phone:
        payload_types.append("Phone")
    if p.permission_request_count > 0:
        payload_types.append("Permission")

    message = {
        "threat_score": threat.threat_score,
        "threat_missing": threat.threat_missing,
        "scam_type": threat.scam_type,
        "intent_confidence": threat.intent_confidence,
        "urgency_score": shared.message_features.urgency_score,
        "authority_score": shared.message_features.authority_score,
        "reward_score": shared.message_features.reward_score,
        "fear_score": shared.message_features.fear_score,
        "obfuscation_flag": shared.message_features.obfuscation_flag,
    }
    return GraphWriteback(
        message=message,
        intent=threat.scam_type,
        payload_types=payload_types,
    )


_predictor: ThreatPredictor | None = None


def get_predictor(model_path: Path | None = None) -> ThreatPredictor:
    global _predictor
    if _predictor is None or (model_path and Path(model_path) != _predictor.model_path):
        _predictor = ThreatPredictor(model_path)
    return _predictor
