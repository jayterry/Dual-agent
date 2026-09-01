"""Context 可學習模型：圖訊號／人設特徵 → context_score（非威脅融合）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import OneHotEncoder

from dual_agent.dai.fraud_dual.ml.dataset import ContextSample, load_context_samples
from dual_agent.dai.fraud_dual.shared.constants import (
    AGE_BANDS,
    CHANNELS,
    OCCUPATIONS,
    RELATION_TYPES,
    SCAM_TYPES,
)
from dual_agent.dai.fraud_dual.shared.features.payload_features import extract_payload_features
from dual_agent.dai.fraud_dual.shared.features.rhetoric_features import extract_rhetoric_features

from dual_agent.dai.fraud_dual.paths import CONTEXT_MODEL_PATH, MODELS_DIR

DEFAULT_MODEL_DIR = MODELS_DIR
DEFAULT_CONTEXT_MODEL = CONTEXT_MODEL_PATH


def _invest_flag(raw: str | None) -> float:
    if raw is None:
        return 0.5
    s = str(raw).strip().lower()
    if s in {"", "none", "no", "0", "無", "沒有"}:
        return 0.0
    if s in {"有", "yes", "1", "豐富", "普通"}:
        return 1.0 if s != "普通" else 0.6
    return 0.5


def context_feature_matrix(
    samples: list[ContextSample],
    encoder: OneHotEncoder | None = None,
    *,
    fit: bool = False,
) -> tuple[np.ndarray, OneHotEncoder]:
    cat = np.array(
        [
            [s.age_band, s.occupation, s.relation_type, s.channel, s.scam_type]
            for s in samples
        ],
        dtype=object,
    )
    if encoder is None:
        encoder = OneHotEncoder(
            categories=[
                list(AGE_BANDS),
                list(OCCUPATIONS),
                list(RELATION_TYPES),
                list(CHANNELS),
                list(SCAM_TYPES),
            ],
            handle_unknown="ignore",
            sparse_output=False,
        )
    if fit:
        X_cat = encoder.fit_transform(cat)
    else:
        X_cat = encoder.transform(cat)

    nums: list[list[float]] = []
    for s in samples:
        rh = extract_rhetoric_features(s.text)
        pf = extract_payload_features(s.text)
        nums.append(
            [
                float(s.channel_is_familiar),
                _invest_flag(s.invest_exp),
                rh.urgency_score,
                rh.authority_score,
                rh.reward_score,
                rh.fear_score,
                float(rh.obfuscation_flag),
                pf.payload_risk_score,
                float(pf.contains_url),
                float(pf.url_is_shortener),
                float(pf.contains_apk),
            ]
        )
    X_num = np.asarray(nums, dtype=np.float64)
    return np.hstack([X_cat, X_num]), encoder


def signals_to_context_vector(signals: dict, encoder: OneHotEncoder) -> np.ndarray:
    """推論時由 graph.extract_signals() 組向量。"""
    age = signals.get("age_band") or "25-39"
    occ = signals.get("occupation") or "other"
    rel = signals.get("relation_type") or "Unknown"
    ch = signals.get("channel") or "LINE"
    scam = signals.get("scam_type") or "Unknown"
    cat = np.array([[age, occ, rel, ch, scam]], dtype=object)
    X_cat = encoder.transform(cat)
    invest = signals.get("invest_exp")
    X_num = np.asarray(
        [
            [
                float(signals.get("channel_is_familiar") or 0),
                _invest_flag(None if invest in ("", None) else str(invest)),
                float(signals.get("urgency_score") or 0.0),
                float(signals.get("authority_score") or 0.0),
                float(signals.get("reward_score") or 0.0),
                float(signals.get("fear_score") or 0.0),
                0.0,
                float(signals.get("payload_risk_score") or 0.0),
                1.0 if float(signals.get("payload_risk_score") or 0) > 0 else 0.0,
                0.0,
                0.0,
            ]
        ],
        dtype=np.float64,
    )
    return np.hstack([X_cat, X_num])


def train_context_model(
    model_dir: Path | None = None,
    *,
    csv_path: Path | None = None,
    random_state: int = 42,
    test_size: float = 0.2,
) -> Path:
    model_dir = Path(model_dir or DEFAULT_MODEL_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)

    samples = load_context_samples(csv_path)
    if len(samples) < 50:
        raise RuntimeError(f"Too few context samples: {len(samples)}")

    groups = np.array([s.text for s in samples])
    y = np.asarray([s.context_score for s in samples], dtype=float)
    gss = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_idx, test_idx = next(gss.split(np.arange(len(samples)), y, groups))

    train_s = [samples[i] for i in train_idx]
    test_s = [samples[i] for i in test_idx]
    X_tr, enc = context_feature_matrix(train_s, fit=True)
    X_te, _ = context_feature_matrix(test_s, encoder=enc, fit=False)
    y_tr, y_te = y[train_idx], y[test_idx]

    model = HistGradientBoostingRegressor(
        max_depth=6,
        learning_rate=0.08,
        max_iter=200,
        random_state=random_state,
    )
    model.fit(X_tr, y_tr)
    pred = np.clip(model.predict(X_te), 0.0, 1.0)
    metrics: dict[str, Any] = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "backend": "hist_gbdt_v1",
        "n_total": len(samples),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "test_size": test_size,
        "random_state": random_state,
        "mae": float(mean_absolute_error(y_te, pred)),
        "r2": float(r2_score(y_te, pred)),
        "note": "Labels from rules_v1 teacher; split grouped by message content.",
    }

    bundle = {
        "model": model,
        "encoder": enc,
        "version": "context_histgbdt_v1",
        "metrics": metrics,
    }
    out = model_dir / "context_model.joblib"
    joblib.dump(bundle, out)
    (model_dir / "context_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out
