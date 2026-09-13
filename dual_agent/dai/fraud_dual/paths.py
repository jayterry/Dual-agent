"""fraud_dual 套件路徑：模型與倉庫根目錄。"""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
# dual_agent/dai/fraud_dual → Dual-agent repo root
REPO_ROOT = PACKAGE_ROOT.parents[2]
MODELS_DIR = REPO_ROOT / "data" / "fraud_dual_models"

THREAT_MODEL_PATH = MODELS_DIR / "threat_models.joblib"
CONTEXT_MODEL_PATH = MODELS_DIR / "context_model.joblib"
HETERO_MODEL_PATH = MODELS_DIR / "context_hetero.pt"
HETERO_RANKING_FULL_PATH = MODELS_DIR / "context_hetero_ranking_full.pt"


def resolve_hetero_model_path() -> Path | None:
    """產品載入順序：DAI_HETERO_MODEL_PATH → ranking_full → context_hetero.pt。"""
    import os

    env = os.environ.get("DAI_HETERO_MODEL_PATH", "").strip()
    if env:
        p = Path(env)
        return p if p.exists() else None
    if HETERO_RANKING_FULL_PATH.exists():
        return HETERO_RANKING_FULL_PATH
    if HETERO_MODEL_PATH.exists():
        return HETERO_MODEL_PATH
    return None
