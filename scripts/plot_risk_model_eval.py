#!/usr/bin/env python3
"""離線評估：標註 vs ML 輸出、legacy vs ML、ROC 曲線。"""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.dai.risk_analysis.ml.feature_spec import all_feature_names

_DEFAULT_FEATURES = _ROOT / "data" / "risk_training" / "features_synthetic.csv"
_MODEL_DIRS = {
    "sklearn": _ROOT / "data" / "risk_models" / "lr_v0",
    "gd": _ROOT / "data" / "risk_models" / "lr_v0_gd",
}
_DEFAULT_MODEL = _MODEL_DIRS["sklearn"] / "model.pkl"
_DEFAULT_OUT = _MODEL_DIRS["sklearn"] / "eval_plots"

WARN_THRESHOLD = 70
BLOCK_THRESHOLD = 85


def _dataset_subtitle(rows: list[dict[str, str]]) -> str:
    n = len(rows)
    n_scam = sum(1 for r in rows if int(r.get("y_scam") or 0) == 1)
    n_benign = n - n_scam
    n_train = sum(1 for r in rows if str(r.get("split") or "") == "train")
    n_val = sum(1 for r in rows if str(r.get("split") or "") == "val")
    n_test = sum(1 for r in rows if str(r.get("split") or "") == "test")
    return (
        f"共 {n} 筆（答案：scam={n_scam}、benign={n_benign}；"
        f"train={n_train}、val={n_val}、test={n_test}）｜模擬標註，僅供管線驗證"
    )


def _answer_marker_legend_handles(*, include_thresholds: bool = False) -> list:
    from matplotlib.lines import Line2D

    handles = [
        Line2D(
            [0], [0], marker="o", color="w", markerfacecolor="#d62728", markersize=8,
            label="紅色＝標準答案 scam",
        ),
        Line2D(
            [0], [0], marker="o", color="w", markerfacecolor="#1f77b4", markersize=8,
            label="藍色＝標準答案 benign",
        ),
        Line2D(
            [0], [0], marker="o", color="w", markerfacecolor="gray", markersize=8,
            label="圓形 ○＝train",
        ),
        Line2D(
            [0], [0], marker="^", color="w", markerfacecolor="gray", markersize=8,
            label="三角 △＝val",
        ),
    ]
    if include_thresholds:
        handles.extend([
            Line2D([0], [0], color="#ff7f0e", linestyle="--", label=f"warn={WARN_THRESHOLD}"),
            Line2D([0], [0], color="#d62728", linestyle="--", label=f"block={BLOCK_THRESHOLD}"),
        ])
    return handles


def model_dir_for_solver(solver: str) -> Path:
    if solver not in _MODEL_DIRS:
        raise ValueError(f"未知 solver: {solver}，請用 sklearn 或 gd")
    return _MODEL_DIRS[solver]


def _solver_label_from_pipe(pipe: object) -> str:
    steps = getattr(pipe, "named_steps", None)
    if steps is None:
        return "unknown"
    clf = steps.get("clf")
    if clf is not None and getattr(clf, "solver_", None) == "gd":
        return "GD（梯度下降）"
    return "sklearn"


def _plot_stamp(pipe: object) -> str:
    label = _solver_label_from_pipe(pipe)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"{label} · {ts}"


def _configure_matplotlib() -> None:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    candidates = [
        "Microsoft JhengHei",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK TC",
        "Arial Unicode MS",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, *plt.rcParams["font.sans-serif"]]
            break
    plt.rcParams["axes.unicode_minus"] = False


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _rows_to_x(rows: list[dict[str, str]]) -> list[list[float]]:
    feature_names = list(all_feature_names())
    return [[float(row.get(n) or 0) for n in feature_names] for row in rows]


def _marker_for_split(split: str) -> str:
    return "^" if split == "val" else "o"


def _color_for_label(y_scam: int) -> str:
    return "#d62728" if y_scam == 1 else "#1f77b4"


def plot_label_vs_ml_proba(
    rows: list[dict[str, str]], ml_scores: list[float], out: Path, *, stamp: str = ""
) -> Path:
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(9, 5))

    rng = np.random.default_rng(42)
    for row, score in zip(rows, ml_scores, strict=True):
        y = int(row.get("y_scam") or 0)
        split = str(row.get("split") or "train")
        jitter = rng.uniform(-0.08, 0.08)
        ax.scatter(
            score,
            y + jitter,
            c=_color_for_label(y),
            marker=_marker_for_split(split),
            s=70,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.5,
        )

    ax.axvline(WARN_THRESHOLD, color="#ff7f0e", linestyle="--", linewidth=1, label=f"warn={WARN_THRESHOLD}")
    ax.axvline(BLOCK_THRESHOLD, color="#d62728", linestyle="--", linewidth=1, label=f"block={BLOCK_THRESHOLD}")

    ax.set_xlim(-5, 105)
    ax.set_ylim(-0.25, 1.25)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["benign (0)", "scam (1)"])
    ax.set_xlabel("ML P(fraud) × 100")
    ax.set_ylabel("標註 y_scam")
    title = "標註答案 vs ML 預測機率"
    if stamp:
        title = f"標註答案 vs ML 預測機率（n={len(rows)}）\n[{stamp}]"
    else:
        title = f"標註答案 vs ML 預測機率（n={len(rows)}）"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    ax.legend(handles=_answer_marker_legend_handles(include_thresholds=True), loc="upper left", fontsize=8)
    fig.text(0.5, 0.01, _dataset_subtitle(rows), ha="center", fontsize=8, color="gray")

    path = out / "label_vs_ml_proba.png"
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_legacy_vs_ml(
    rows: list[dict[str, str]], ml_scores: list[float], out: Path, *, stamp: str = ""
) -> Path:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 7))

    for row, ml_score in zip(rows, ml_scores, strict=True):
        legacy = float(row.get("legacy_risk_score") or 0)
        y = int(row.get("y_scam") or 0)
        split = str(row.get("split") or "train")
        ax.scatter(
            legacy,
            ml_score,
            c=_color_for_label(y),
            marker=_marker_for_split(split),
            s=70,
            alpha=0.85,
            edgecolors="white",
            linewidths=0.5,
        )

    ax.plot([0, 100], [0, 100], color="gray", linestyle="--", linewidth=1, label="y = x（兩者一致）")

    ax.set_xlim(-5, 105)
    ax.set_ylim(-5, 105)
    ax.set_xlabel("legacy_risk_score（現行公式）")
    ax.set_ylabel("ml_score（LR 校準）")
    title = f"現行公式 vs ML 風險分（n={len(rows)}）"
    if stamp:
        title += f"\n[{stamp}]"
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.3)

    from matplotlib.lines import Line2D

    handles = _answer_marker_legend_handles() + [
        Line2D([0], [0], color="gray", linestyle="--", label="y = x（兩者一致）"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=7)
    fig.text(0.5, 0.01, _dataset_subtitle(rows), ha="center", fontsize=8, color="gray")

    path = out / "legacy_vs_ml_score.png"
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_roc(rows: list[dict[str, str]], ml_probas: list[float], out: Path, *, stamp: str = "") -> Path:
    import matplotlib.pyplot as plt
    from sklearn.metrics import auc, roc_curve

    fig, ax = plt.subplots(figsize=(7, 7))

    for split_name, color in (("train", "#1f77b4"), ("val", "#ff7f0e")):
        indices = [i for i, r in enumerate(rows) if str(r.get("split") or "") == split_name]
        if not indices:
            continue
        ys = [int(rows[i].get("y_scam") or 0) for i in indices]
        probas = [ml_probas[i] for i in indices]
        n = len(ys)
        if len(set(ys)) < 2:
            ax.scatter([], [], label=f"{split_name} (n={n}, 單類別無 ROC)")
            continue
        fpr, tpr, _ = roc_curve(ys, probas)
        roc_auc = auc(fpr, tpr)
        ax.plot(fpr, tpr, color=color, linewidth=2, label=f"{split_name} (n={n}, AUC={roc_auc:.3f})")

    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1, label="random")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("FPR（假陽性率）")
    ax.set_ylabel("TPR（真陽性率）")
    title = f"ROC 曲線（n={len(rows)}）"
    if stamp:
        title += f"\n[{stamp}]"
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right", fontsize=8)
    fig.text(0.5, 0.01, _dataset_subtitle(rows), ha="center", fontsize=8, color="gray")

    path = out / "roc_curve.png"
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def plot_answer_prediction_distribution(
    rows: list[dict[str, str]],
    ml_scores: list[float],
    out: Path,
    *,
    stamp: str = "",
) -> Path:
    """答案分布 + 預測分布 + 依答案分組的預測分數直方圖。"""
    import matplotlib.pyplot as plt
    import numpy as np

    y_scam = [int(r.get("y_scam") or 0) for r in rows]
    pred_label = [1 if s >= 50 else 0 for s in ml_scores]

    n_benign_ans = sum(1 for y in y_scam if y == 0)
    n_scam_ans = sum(1 for y in y_scam if y == 1)
    n_pred_benign = sum(1 for p in pred_label if p == 0)
    n_pred_scam = sum(1 for p in pred_label if p == 1)

    scores_benign = [s for s, y in zip(ml_scores, y_scam, strict=True) if y == 0]
    scores_scam = [s for s, y in zip(ml_scores, y_scam, strict=True) if y == 1]

    # confusion: rows=答案, cols=預測
    tn = sum(1 for y, p in zip(y_scam, pred_label, strict=True) if y == 0 and p == 0)
    fp = sum(1 for y, p in zip(y_scam, pred_label, strict=True) if y == 0 and p == 1)
    fn = sum(1 for y, p in zip(y_scam, pred_label, strict=True) if y == 1 and p == 0)
    tp = sum(1 for y, p in zip(y_scam, pred_label, strict=True) if y == 1 and p == 1)
    cm = np.array([[tn, fp], [fn, tp]])

    fig = plt.figure(figsize=(11, 9))
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1.2], hspace=0.35, wspace=0.3)

    ax_ans = fig.add_subplot(gs[0, 0])
    ax_ans.bar(
        ["benign\n(答案)", "scam\n(答案)"],
        [n_benign_ans, n_scam_ans],
        color=["#1f77b4", "#d62728"],
        width=0.55,
    )
    ax_ans.set_ylabel("樣本數")
    ax_ans.set_title("① 標準答案分布")
    for i, v in enumerate([n_benign_ans, n_scam_ans]):
        ax_ans.text(i, v + 0.3, str(v), ha="center", fontsize=10)

    ax_pred = fig.add_subplot(gs[0, 1])
    ax_pred.bar(
        ["benign\n(預測)", "scam\n(預測)"],
        [n_pred_benign, n_pred_scam],
        color=["#1f77b4", "#d62728"],
        width=0.55,
    )
    ax_pred.set_ylabel("樣本數")
    ax_pred.set_title("② 模型預測類別分布（分數≥50）")
    for i, v in enumerate([n_pred_benign, n_pred_scam]):
        ax_pred.text(i, v + 0.3, str(v), ha="center", fontsize=10)

    ax_cm = fig.add_subplot(gs[1, 0])
    im = ax_cm.imshow(cm, cmap="Blues", vmin=0)
    ax_cm.set_xticks([0, 1])
    ax_cm.set_yticks([0, 1])
    ax_cm.set_xticklabels(["預測 benign", "預測 scam"])
    ax_cm.set_yticklabels(["答案 benign", "答案 scam"])
    ax_cm.set_title("③ 答案 × 預測 對照（≥50）")
    for i in range(2):
        for j in range(2):
            ax_cm.text(j, i, str(int(cm[i, j])), ha="center", va="center", fontsize=14, color="black")
    fig.colorbar(im, ax=ax_cm, fraction=0.046, pad=0.04)

    ax_hist = fig.add_subplot(gs[1, 1])
    bins = np.linspace(0, 100, 21)
    ax_hist.hist(
        scores_benign,
        bins=bins,
        alpha=0.65,
        color="#1f77b4",
        label=f"答案=benign (n={len(scores_benign)})",
        edgecolor="white",
    )
    ax_hist.hist(
        scores_scam,
        bins=bins,
        alpha=0.65,
        color="#d62728",
        label=f"答案=scam (n={len(scores_scam)})",
        edgecolor="white",
    )
    ax_hist.axvline(50, color="#2ca02c", linestyle=":", linewidth=1, label="分類門檻=50")
    ax_hist.axvline(WARN_THRESHOLD, color="#ff7f0e", linestyle="--", linewidth=1, label=f"warn={WARN_THRESHOLD}")
    ax_hist.axvline(BLOCK_THRESHOLD, color="#d62728", linestyle="--", linewidth=1, label=f"block={BLOCK_THRESHOLD}")
    ax_hist.set_xlabel("ML 預測分數")
    ax_hist.set_ylabel("樣本數")
    ax_hist.set_title("④ 預測分數分布（顏色=標準答案）")
    ax_hist.legend(loc="upper left", fontsize=7)
    ax_hist.grid(True, alpha=0.25)

    title = f"答案與預測結果分布（n={len(rows)}）"
    if stamp:
        title += f"\n[{stamp}]"
    fig.suptitle(title, fontsize=12, y=0.98)
    fig.text(0.5, 0.01, _dataset_subtitle(rows), ha="center", fontsize=8, color="gray")

    path = out / "answer_vs_prediction_dist.png"
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def run_eval(
    features_path: Path,
    model_path: Path,
    out_dir: Path,
) -> list[Path]:
    try:
        import matplotlib.pyplot as plt  # noqa: F401
    except ImportError as e:
        raise SystemExit("請安裝 matplotlib：pip install matplotlib") from e

    _configure_matplotlib()

    if not features_path.is_file():
        raise SystemExit(f"找不到特徵檔：{features_path}")
    if not model_path.is_file():
        raise SystemExit(f"找不到模型：{model_path}")

    rows = _load_csv(features_path)
    if not rows:
        raise SystemExit(f"空特徵檔：{features_path}")

    with model_path.open("rb") as f:
        pipe = pickle.load(f)

    stamp = _plot_stamp(pipe)
    x = _rows_to_x(rows)
    ml_probas = pipe.predict_proba(x)[:, 1].tolist()
    ml_scores = [round(p * 100, 1) for p in ml_probas]

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        plot_answer_prediction_distribution(rows, ml_scores, out_dir, stamp=stamp),
        plot_label_vs_ml_proba(rows, ml_scores, out_dir, stamp=stamp),
        plot_legacy_vs_ml(rows, ml_scores, out_dir, stamp=stamp),
        plot_roc(rows, ml_probas, out_dir, stamp=stamp),
    ]
    print(f"模型：{model_path}")
    print(f"標記：{stamp}")
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot ML risk model evaluation charts")
    parser.add_argument("--features", type=Path, default=_DEFAULT_FEATURES)
    parser.add_argument(
        "--solver",
        choices=("sklearn", "gd"),
        default=None,
        help="捷徑：自動選 model/out 目錄（lr_v0 或 lr_v0_gd）",
    )
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.solver:
        base = model_dir_for_solver(args.solver)
        model = args.model or (base / "model.pkl")
        out = args.out or (base / "eval_plots")
    else:
        model = args.model or _DEFAULT_MODEL
        out = args.out or _DEFAULT_OUT

    paths = run_eval(args.features, model, out)
    for p in paths:
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
