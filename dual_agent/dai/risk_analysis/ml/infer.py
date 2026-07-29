"""線上 ML 風險融合：載入 LR／RF pipeline，產出 p_fraud 與分數。"""

from __future__ import annotations

import pickle
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dual_agent.config import dai_ml_model_path, dai_risk_fusion_mode
from dual_agent.dai.risk_analysis.ml.feature_extractor import extract_features
from dual_agent.dai.risk_analysis.verdict import MachineFusionParts, RiskFusionResult, compute_r_machine, scale_llm_score_to_100

_lock = threading.Lock()
_cache: dict[str, Any] = {}


@dataclass(frozen=True)
class MlFusionResult:
    fusion: RiskFusionResult
    p_fraud: float
    model_path: str
    mode: str
    feature_snapshot: dict[str, float]


def clear_model_cache() -> None:
    with _lock:
        _cache.clear()


def load_risk_model(path: str | Path | None = None) -> Any:
    p = Path(path or dai_ml_model_path())
    key = str(p.resolve()) if p.exists() else str(p)
    with _lock:
        if key in _cache:
            return _cache[key]
        if not p.is_file():
            raise FileNotFoundError(f"找不到 ML 模型：{p}")
        with p.open("rb") as f:
            model = pickle.load(f)
        _cache[key] = model
        return model


def fuse_risk_score_ml(
    *,
    text: str,
    component_scores: dict[str, int],
    rules_hits: list[dict[str, Any]],
    semantic: dict[str, Any] | None = None,
    toxic_meta: dict[str, Any] | None = None,
    url_threat_hits: list[dict[str, Any]] | None = None,
    missing_evidence: list[str] | None = None,
    source: str = "desktop",
    phones: list[str] | None = None,
    amounts: list[str] | None = None,
    urls: list[str] | None = None,
    model_path: str | None = None,
    mode: str | None = None,
) -> MlFusionResult:
    """
    以已訓練 pipeline 推論 P(fraud)，映射 0–100；
    r_rules / r_threat_intel ≥ 85 時硬擋（不得被 ML 洗低）。
    """
    mode_s = (mode or dai_risk_fusion_mode()).strip().lower()
    path = model_path or dai_ml_model_path()
    cs = {k: int(component_scores.get(k) or 0) for k in (
        "r_rules",
        "r_threat_intel",
        "r_tls",
        "r_toxic_fused",
        "tier_h",
        "tier_i",
        "r_llm_optional",
    )}
    machine = compute_r_machine(
        r_rules=cs["r_rules"],
        r_threat_intel=cs["r_threat_intel"],
        r_tls=cs["r_tls"],
        r_toxic_fused=cs["r_toxic_fused"],
    )
    r_llm_100 = scale_llm_score_to_100(
        cs["r_llm_optional"],
        tier_h=cs["tier_h"],
        tier_i=cs["tier_i"],
    )

    fv = extract_features(
        text=text,
        component_scores=cs,
        rules_hits=rules_hits,
        semantic=semantic,
        toxic_meta=toxic_meta,
        url_threat_hits=url_threat_hits,
        missing_evidence=missing_evidence,
        source=source,
        phones=phones,
        amounts=amounts,
        urls=urls,
    )
    model = load_risk_model(path)
    x = [fv.to_list()]
    if hasattr(model, "predict_proba"):
        p_fraud = float(model.predict_proba(x)[0][1])
    else:
        pred = float(model.predict(x)[0])
        p_fraud = max(0.0, min(1.0, pred))

    fused = max(0, min(100, int(round(p_fraud * 100))))
    hard_guard_applied = False
    hard = max(cs["r_rules"], cs["r_threat_intel"])
    if hard >= 85:
        if fused < hard:
            hard_guard_applied = True
        fused = max(fused, hard)

    fusion = RiskFusionResult(
        r_fused=fused,
        r_llm_100=r_llm_100,
        machine=machine,
        hard_guard_applied=hard_guard_applied,
    )
    return MlFusionResult(
        fusion=fusion,
        p_fraud=round(p_fraud, 6),
        model_path=str(path),
        mode=mode_s if mode_s.startswith("ml") else "ml_lr",
        feature_snapshot={k: float(v) for k, v in list(fv.to_dict().items())[:24]},
    )
