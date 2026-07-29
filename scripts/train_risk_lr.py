#!/usr/bin/env python3
"""訓練 Logistic Regression 風險模型（sklearn 或自實作梯度下降）。"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.dai.risk_analysis.ml.feature_spec import FEATURE_SPEC_VERSION, all_feature_names
from dual_agent.dai.risk_analysis.ml.gradient_descent_lr import LogisticRegressionGD

_DEFAULT_FEATURES = _ROOT / "data" / "risk_training" / "features_synthetic.csv"
_DEFAULT_OUT_SKLEARN = _ROOT / "data" / "risk_models" / "lr_v0"
_DEFAULT_OUT_GD = _ROOT / "data" / "risk_models" / "lr_v0_gd"


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _rows_to_xy(
    rows: list[dict[str, str]],
    *,
    split: str | None = None,
) -> tuple[list[list[float]], list[int]]:
    feature_names = list(all_feature_names())
    xs: list[list[float]] = []
    ys: list[int] = []
    for row in rows:
        if split and str(row.get("split") or "") != split:
            continue
        y = int(row.get("y_scam") or 0)
        xs.append([float(row.get(n) or 0) for n in feature_names])
        ys.append(y)
    return xs, ys


def _build_pipeline(solver: str, *, lr: float, epochs: int, l2: float) -> Any:
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if solver == "gd":
        clf: Any = LogisticRegressionGD(
            learning_rate=lr,
            n_epochs=epochs,
            l2_lambda=l2,
            class_weight="balanced",
        )
    elif solver == "sklearn":
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(
            class_weight="balanced",
            max_iter=2000,
            random_state=42,
        )
    else:
        raise ValueError(f"未知 solver: {solver}")

    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", clf),
        ]
    )


def _eval_metrics(pipe: Any, x: list[list[float]], y: list[int], prefix: str, metrics: dict[str, object]) -> None:
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    if not x:
        return
    proba = pipe.predict_proba(x)[:, 1]
    pred = pipe.predict(x)
    metrics[f"{prefix}_accuracy"] = round(float(accuracy_score(y, pred)), 4)
    metrics[f"{prefix}_f1"] = round(float(f1_score(y, pred, zero_division=0)), 4)
    metrics[f"{prefix}_precision"] = round(float(precision_score(y, pred, zero_division=0)), 4)
    metrics[f"{prefix}_recall"] = round(float(recall_score(y, pred, zero_division=0)), 4)
    if len(set(y)) > 1:
        metrics[f"{prefix}_auc"] = round(float(roc_auc_score(y, proba)), 4)


def train_lr(
    features_path: Path,
    out_dir: Path,
    *,
    solver: str = "sklearn",
    learning_rate: float = 0.1,
    n_epochs: int = 2000,
    l2_lambda: float = 0.01,
) -> dict[str, object]:
    try:
        import sklearn  # noqa: F401
    except ImportError as e:
        raise SystemExit("請安裝 scikit-learn：pip install scikit-learn") from e

    rows = _load_csv(features_path)
    if not rows:
        raise SystemExit(f"空特徵檔：{features_path}")

    x_train, y_train = _rows_to_xy(rows, split="train")
    x_val, y_val = _rows_to_xy(rows, split="val")
    if not x_train:
        x_train, y_train = _rows_to_xy(rows)
        x_val, y_val = [], []

    pipe = _build_pipeline(solver, lr=learning_rate, epochs=n_epochs, l2=l2_lambda)
    pipe.fit(x_train, y_train)

    metrics: dict[str, object] = {
        "feature_spec_version": FEATURE_SPEC_VERSION,
        "solver": solver,
        "n_train": len(y_train),
        "n_val": len(y_val),
        "feature_names": list(all_feature_names()),
    }
    if solver == "gd":
        metrics["gd_learning_rate"] = learning_rate
        metrics["gd_n_epochs"] = n_epochs
        metrics["gd_l2_lambda"] = l2_lambda

    _eval_metrics(pipe, x_train, y_train, "train", metrics)
    _eval_metrics(pipe, x_val, y_val, "val", metrics)

    clf = pipe.named_steps["clf"]
    coefs = clf.coef_[0]
    coefficients = {
        name: round(float(c), 6)
        for name, c in zip(all_feature_names(), coefs, strict=True)
    }
    top = sorted(coefficients.items(), key=lambda kv: abs(kv[1]), reverse=True)[:15]

    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / "model.pkl"
    with model_path.open("wb") as f:
        pickle.dump(pipe, f)

    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "coefficients.json").write_text(
        json.dumps(
            {"coefficients": coefficients, "top_abs_15": top},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "feature_spec_version.txt").write_text(FEATURE_SPEC_VERSION + "\n", encoding="utf-8")

    if solver == "gd" and hasattr(clf, "loss_history_"):
        loss_hist = [round(float(v), 6) for v in clf.loss_history_]
        (out_dir / "loss_history.json").write_text(
            json.dumps(
                {
                    "n_epochs_run": clf.n_iter_,
                    "final_loss": loss_hist[-1] if loss_hist else None,
                    "loss_history": loss_hist,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        metrics["gd_n_epochs_run"] = clf.n_iter_
        metrics["gd_final_loss"] = loss_hist[-1] if loss_hist else None

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Train logistic regression risk model")
    parser.add_argument("--features", type=Path, default=_DEFAULT_FEATURES)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--solver",
        choices=("sklearn", "gd"),
        default="sklearn",
        help="sklearn=內建求解器；gd=自實作批次梯度下降",
    )
    parser.add_argument("--lr", type=float, default=0.1, help="GD 學習率（僅 --solver gd）")
    parser.add_argument("--epochs", type=int, default=2000, help="GD 最大 epoch 數")
    parser.add_argument("--l2", type=float, default=0.01, help="GD L2 正則係數")
    parser.add_argument("--no-plots", action="store_true", help="訓練後不自動產圖")
    args = parser.parse_args()

    out = args.out
    if out is None:
        out = _DEFAULT_OUT_GD if args.solver == "gd" else _DEFAULT_OUT_SKLEARN

    metrics = train_lr(
        args.features,
        out,
        solver=args.solver,
        learning_rate=args.lr,
        n_epochs=args.epochs,
        l2_lambda=args.l2,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"Model saved to {out / 'model.pkl'}")

    if not args.no_plots:
        import subprocess

        plot_dir = out / "eval_plots"
        plot_eval = [
            sys.executable,
            str(_ROOT / "scripts" / "plot_risk_model_eval.py"),
            "--features",
            str(args.features),
            "--model",
            str(out / "model.pkl"),
            "--out",
            str(plot_dir),
        ]
        subprocess.run(plot_eval, check=False)
        if args.solver == "gd":
            subprocess.run(
                [
                    sys.executable,
                    str(_ROOT / "scripts" / "plot_gd_loss.py"),
                    "--loss",
                    str(out / "loss_history.json"),
                    "--out",
                    str(plot_dir),
                ],
                check=False,
            )
        # 係數視覺化
        coef_path = out / "coefficients.json"
        if coef_path.is_file():
            subprocess.run(
                [
                    sys.executable,
                    str(_ROOT / "scripts" / "plot_lr_coefficients.py"),
                    "--coefficients",
                    str(coef_path),
                    "--out",
                    str(plot_dir),
                ],
                check=False,
            )


if __name__ == "__main__":
    main()
