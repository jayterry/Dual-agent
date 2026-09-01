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
