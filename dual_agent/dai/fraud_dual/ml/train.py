"""訓練 XGBoost（scam_type）+ LR（threat_score）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
    mean_absolute_error,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from xgboost import XGBClassifier

from dual_agent.dai.fraud_dual.ml.dataset import ThreatSample, load_threat_samples
from dual_agent.dai.fraud_dual.ml.synthetic import SyntheticSample, build_synthetic_corpus
from dual_agent.dai.fraud_dual.ml.vectorize import structured_vector
from dual_agent.dai.fraud_dual.shared.features import extract_shared
from dual_agent.dai.fraud_dual.shared.schemas import BuildGraphInput

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
DataSource = Literal["persona_csv", "synthetic", "auto"]


def _sample_to_shared(text: str, *, age_band: str, occupation: str, relation_type: str, channel: str, primary_apps: tuple[str, ...] | list[str], invest_exp: str | None = None):
    build = BuildGraphInput(
        age_band=age_band,  # type: ignore[arg-type]
        occupation=occupation,  # type: ignore[arg-type]
        relation_type=relation_type,  # type: ignore[arg-type]
        channel=channel,  # type: ignore[arg-type]
        primary_apps=list(primary_apps),  # type: ignore[arg-type]
        invest_exp=invest_exp,
    )
    return extract_shared(text, build)


def _threat_from_synthetic(samples: list[SyntheticSample]) -> list[ThreatSample]:
    return [
        ThreatSample(
            text=s.text,
            scam_type=s.scam_type,
            threat_score=s.threat_score,
            age_band=s.age_band,
            occupation=s.occupation,
            relation_type=s.relation_type,
            channel=s.channel,
            primary_apps=tuple(s.primary_apps),
            invest_exp=None,
            persona_role="synthetic",
        )
        for s in samples
    ]


def _build_matrices(samples: list[ThreatSample]):
    texts: list[str] = []
    structs: list[np.ndarray] = []
    y_type: list[str] = []
    y_threat_bin: list[int] = []
    y_threat_soft: list[float] = []
    for s in samples:
        shared = _sample_to_shared(
            s.text,
            age_band=s.age_band,
            occupation=s.occupation,
            relation_type=s.relation_type,
            channel=s.channel,
            primary_apps=s.primary_apps,
            invest_exp=s.invest_exp,
        )
        texts.append(s.text)
        structs.append(structured_vector(shared))
        y_type.append(s.scam_type)
        y_threat_bin.append(1 if s.threat_score >= 0.5 else 0)
        y_threat_soft.append(s.threat_score)
    X_struct = np.vstack(structs)
    return (
        texts,
        X_struct,
        y_type,
        np.asarray(y_threat_bin, dtype=int),
        np.asarray(y_threat_soft, dtype=float),
    )


def resolve_samples(data_source: DataSource = "auto", csv_path: Path | None = None) -> tuple[list[ThreatSample], str]:
    if data_source == "synthetic":
        return _threat_from_synthetic(build_synthetic_corpus()), "synthetic"
    if data_source == "persona_csv":
        return load_threat_samples(csv_path), "persona_csv"
    # auto
    try:
        return load_threat_samples(csv_path), "persona_csv"
    except FileNotFoundError:
        return _threat_from_synthetic(build_synthetic_corpus()), "synthetic"


def train_and_save(
    model_dir: Path | None = None,
    random_state: int = 42,
    *,
    data_source: DataSource = "auto",
    csv_path: Path | None = None,
    test_size: float = 0.2,
    write_metrics: bool = True,
) -> Path:
    model_dir = Path(model_dir or DEFAULT_MODEL_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)

    samples, resolved = resolve_samples(data_source, csv_path)
    texts, X_struct, y_type, y_threat_bin, y_threat_soft = _build_matrices(samples)

    idx = np.arange(len(samples))
    train_idx, test_idx = train_test_split(
        idx,
        test_size=test_size,
        random_state=random_state,
        stratify=y_type,
    )

    def _take(arr, ids):
        if isinstance(arr, list):
            return [arr[i] for i in ids]
        return arr[ids]

    texts_tr, texts_te = _take(texts, train_idx), _take(texts, test_idx)
    Xs_tr, Xs_te = X_struct[train_idx], X_struct[test_idx]
    yt_tr = _take(y_type, train_idx)
    yt_te = _take(y_type, test_idx)
    yb_tr, yb_te = y_threat_bin[train_idx], y_threat_bin[test_idx]
    ys_te = y_threat_soft[test_idx]

    tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(2, 4),
        min_df=2 if resolved == "persona_csv" else 1,
        max_features=8000 if resolved == "persona_csv" else 4000,
    )
    X_text_tr = tfidf.fit_transform(texts_tr)
    X_text_te = tfidf.transform(texts_te)

    scaler = StandardScaler()
    Xs_tr_s = scaler.fit_transform(Xs_tr)
    Xs_te_s = scaler.transform(Xs_te)
    X_tr = sparse.hstack([sparse.csr_matrix(Xs_tr_s), X_text_tr], format="csr")
    X_te = sparse.hstack([sparse.csr_matrix(Xs_te_s), X_text_te], format="csr")

    label_encoder = LabelEncoder()
    y_enc_tr = label_encoder.fit_transform(yt_tr)
    y_enc_te = label_encoder.transform(yt_te)

    clf = XGBClassifier(
        n_estimators=120 if resolved == "persona_csv" else 80,
        max_depth=5 if resolved == "persona_csv" else 4,
        learning_rate=0.12,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="multi:softprob",
        eval_metric="mlogloss",
        random_state=random_state,
        n_jobs=2,
    )
    clf.fit(X_tr, y_enc_tr)

    threat_lr = LogisticRegression(
        max_iter=800,
        class_weight="balanced",
        random_state=random_state,
    )
    threat_lr.fit(X_tr, yb_tr)

    # metrics
    pred_type = label_encoder.inverse_transform(clf.predict(X_te))
    type_acc = float(accuracy_score(yt_te, pred_type))
    type_f1_macro = float(f1_score(yt_te, pred_type, average="macro"))
    type_report = classification_report(yt_te, pred_type, digits=4, zero_division=0)

    threat_proba = threat_lr.predict_proba(X_te)[:, 1]
    threat_pred = (threat_proba >= 0.5).astype(int)
    threat_acc = float(accuracy_score(yb_te, threat_pred))
    try:
        threat_auc = float(roc_auc_score(yb_te, threat_proba))
    except ValueError:
        threat_auc = float("nan")
    threat_mae = float(mean_absolute_error(ys_te, threat_proba))

    metrics: dict[str, Any] = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_source": resolved,
        "n_total": len(samples),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "test_size": test_size,
        "random_state": random_state,
        "label_classes": list(label_encoder.classes_),
        "scam_type": {
            "accuracy": type_acc,
            "macro_f1": type_f1_macro,
            "report": type_report,
        },
        "threat": {
            "accuracy@0.5": threat_acc,
            "roc_auc": threat_auc,
            "mae_vs_soft_label": threat_mae,
        },
        "hyperparams": {
            "xgb_n_estimators": clf.n_estimators,
            "xgb_max_depth": clf.max_depth,
            "tfidf_max_features": tfidf.max_features,
        },
    }

    bundle = {
        "tfidf": tfidf,
        "scaler": scaler,
        "label_encoder": label_encoder,
        "xgb": clf,
        "threat_lr": threat_lr,
        "version": f"ml_v2_{resolved}",
        "metrics": metrics,
    }
    out = model_dir / "threat_models.joblib"
    joblib.dump(bundle, out)

    if write_metrics:
        metrics_path = model_dir / "threat_metrics.json"
        metrics_path.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # clear infer cache if present
    try:
        from dual_agent.dai.fraud_dual.ml import infer as infer_mod

        infer_mod._predictor = None  # type: ignore[attr-defined]
    except Exception:
        pass

    return out
