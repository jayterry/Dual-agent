"""梯度下降 Logistic Regression 測試。"""

from __future__ import annotations

import numpy as np

from dual_agent.dai.risk_analysis.ml.gradient_descent_lr import (
    GDConfig,
    LogisticRegressionGD,
    binary_cross_entropy_loss,
    fit_logistic_regression_gd,
)


def test_loss_decreases_on_separable_data() -> None:
    rng = np.random.default_rng(0)
    n = 80
    x0 = rng.normal(-2.0, 0.5, (n // 2, 3))
    x1 = rng.normal(2.0, 0.5, (n // 2, 3))
    x = np.vstack([x0, x1])
    y = np.array([0] * (n // 2) + [1] * (n // 2))

    result = fit_logistic_regression_gd(
        x,
        y,
        config=GDConfig(learning_rate=0.2, n_epochs=500, l2_lambda=0.001),
    )
    assert len(result.loss_history) > 1
    assert result.loss_history[-1] < result.loss_history[0]
    assert result.n_epochs_run <= 500


def test_predict_proba_shape() -> None:
    x = np.array([[0.0, 1.0], [1.0, 0.0], [2.0, -1.0]])
    y = np.array([0, 0, 1])
    clf = LogisticRegressionGD(learning_rate=0.3, n_epochs=300).fit(x, y)
    proba = clf.predict_proba(x)
    assert proba.shape == (3, 2)
    assert np.allclose(proba.sum(axis=1), 1.0)
    assert clf.predict(x).tolist() == [0, 0, 1]


def test_binary_cross_entropy_bounds() -> None:
    y = np.array([0, 1, 1])
    p = np.array([0.1, 0.9, 0.8])
    loss = binary_cross_entropy_loss(y, p)
    assert loss > 0
