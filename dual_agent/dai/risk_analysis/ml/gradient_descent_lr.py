"""二元 Logistic Regression：批次梯度下降（含 L2 正則與類別權重）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -500.0, 500.0)
    return 1.0 / (1.0 + np.exp(-z))


def _balanced_sample_weights(y: np.ndarray) -> np.ndarray:
    y = np.asarray(y, dtype=int)
    n = len(y)
    if n == 0:
        return np.array([], dtype=float)
    counts = np.bincount(y, minlength=2).astype(float)
    counts = np.maximum(counts, 1.0)
    class_w = n / (2.0 * counts)
    return class_w[y]


@dataclass
class GDConfig:
    learning_rate: float = 0.1
    n_epochs: int = 2000
    l2_lambda: float = 0.01
    tol: float = 1e-6
    class_weight: str | None = "balanced"


@dataclass
class GDFitResult:
    weights: np.ndarray
    bias: float
    loss_history: list[float] = field(default_factory=list)
    n_epochs_run: int = 0
    final_loss: float = 0.0


def binary_cross_entropy_loss(
    y: np.ndarray,
    proba: np.ndarray,
    *,
    sample_weights: np.ndarray | None = None,
    weights: np.ndarray | None = None,
    bias: float = 0.0,
    l2_lambda: float = 0.0,
) -> float:
    eps = 1e-12
    p = np.clip(proba, eps, 1.0 - eps)
    y = np.asarray(y, dtype=float)
    if sample_weights is None:
        sample_weights = np.ones_like(y, dtype=float)
    wsum = float(np.sum(sample_weights))
    if wsum <= 0:
        wsum = 1.0
    bce = -np.sum(sample_weights * (y * np.log(p) + (1.0 - y) * np.log(1.0 - p))) / wsum
    reg = 0.0
    if weights is not None and l2_lambda > 0:
        reg = 0.5 * l2_lambda * float(np.dot(weights, weights))
    return float(bce + reg)


def fit_logistic_regression_gd(
    x: np.ndarray,
    y: np.ndarray,
    *,
    config: GDConfig | None = None,
) -> GDFitResult:
    """在已標準化特徵上執行批次梯度下降。"""
    cfg = config or GDConfig()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=int)
    if x.ndim != 2:
        raise ValueError("x 必須為二維矩陣")
    if len(y) != x.shape[0]:
        raise ValueError("x 與 y 樣本數不一致")
    if len(y) == 0:
        raise ValueError("訓練集為空")

    n_samples, n_features = x.shape
    w = np.zeros(n_features, dtype=float)
    b = 0.0

    if cfg.class_weight == "balanced":
        sw = _balanced_sample_weights(y)
    else:
        sw = np.ones(n_samples, dtype=float)
    sw_sum = float(np.sum(sw))
    if sw_sum <= 0:
        sw_sum = 1.0

    loss_history: list[float] = []
    prev_loss = float("inf")

    for epoch in range(cfg.n_epochs):
        z = x @ w + b
        p = _sigmoid(z)
        loss = binary_cross_entropy_loss(
            y,
            p,
            sample_weights=sw,
            weights=w,
            l2_lambda=cfg.l2_lambda,
        )
        loss_history.append(loss)

        error = (p - y.astype(float)) * sw
        grad_w = (x.T @ error) / sw_sum + cfg.l2_lambda * w
        grad_b = float(np.sum(error) / sw_sum)
        w -= cfg.learning_rate * grad_w
        b -= cfg.learning_rate * grad_b

        if abs(prev_loss - loss) < cfg.tol:
            return GDFitResult(
                weights=w,
                bias=b,
                loss_history=loss_history,
                n_epochs_run=epoch + 1,
                final_loss=loss,
            )
        prev_loss = loss

    return GDFitResult(
        weights=w,
        bias=b,
        loss_history=loss_history,
        n_epochs_run=cfg.n_epochs,
        final_loss=loss_history[-1] if loss_history else 0.0,
    )


class LogisticRegressionGD(BaseEstimator, ClassifierMixin):
    """sklearn 風格介面，供 Pipeline 與 pickle 相容。"""

    classes_: np.ndarray
    coef_: np.ndarray
    intercept_: np.ndarray
    n_iter_: int
    loss_history_: list[float]
    solver_: str = "gd"

    def __init__(
        self,
        *,
        learning_rate: float = 0.1,
        n_epochs: int = 2000,
        l2_lambda: float = 0.01,
        tol: float = 1e-6,
        class_weight: str | None = "balanced",
    ) -> None:
        self.learning_rate = learning_rate
        self.n_epochs = n_epochs
        self.l2_lambda = l2_lambda
        self.tol = tol
        self.class_weight = class_weight

    def fit(self, x: np.ndarray, y: np.ndarray) -> LogisticRegressionGD:
        result = fit_logistic_regression_gd(
            x,
            y,
            config=GDConfig(
                learning_rate=self.learning_rate,
                n_epochs=self.n_epochs,
                l2_lambda=self.l2_lambda,
                tol=self.tol,
                class_weight=self.class_weight,
            ),
        )
        self.classes_ = np.array([0, 1])
        self.coef_ = result.weights.reshape(1, -1)
        self.intercept_ = np.array([result.bias])
        self.n_iter_ = result.n_epochs_run
        self.loss_history_ = result.loss_history
        return self

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        z = x @ self.coef_.ravel() + float(self.intercept_[0])
        p1 = _sigmoid(z)
        p0 = 1.0 - p1
        return np.column_stack([p0, p1])

    def predict(self, x: np.ndarray) -> np.ndarray:
        proba = self.predict_proba(x)[:, 1]
        return (proba >= 0.5).astype(int)

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return {
            "learning_rate": self.learning_rate,
            "n_epochs": self.n_epochs,
            "l2_lambda": self.l2_lambda,
            "tol": self.tol,
            "class_weight": self.class_weight,
        }

    def set_params(self, **params: Any) -> LogisticRegressionGD:
        for k, v in params.items():
            setattr(self, k, v)
        return self
