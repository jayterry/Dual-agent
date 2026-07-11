#!/usr/bin/env python3
"""繪製梯度下降訓練 loss 曲線。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_DEFAULT_LOSS = _ROOT / "data" / "risk_models" / "lr_v0_gd" / "loss_history.json"
_DEFAULT_OUT = _ROOT / "data" / "risk_models" / "lr_v0_gd" / "eval_plots"


def _configure_matplotlib() -> None:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for name in ("Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Noto Sans CJK TC"):
        if name in {f.name for f in font_manager.fontManager.ttflist}:
            plt.rcParams["font.sans-serif"] = [name, *plt.rcParams["font.sans-serif"]]
            break
    plt.rcParams["axes.unicode_minus"] = False


def plot_loss_curve(loss_path: Path, out_dir: Path) -> Path:
    import matplotlib.pyplot as plt

    data = json.loads(loss_path.read_text(encoding="utf-8"))
    history = data.get("loss_history") or []
    if not history:
        raise SystemExit(f"loss_history 為空：{loss_path}")

    n_run = data.get("n_epochs_run", len(history))
    final_loss = data.get("final_loss", history[-1])

    fig, ax = plt.subplots(figsize=(9, 5))
    epochs = list(range(1, len(history) + 1))
    ax.plot(epochs, history, color="#1f77b4", linewidth=1.5, label="BCE + L2 loss")
    ax.set_xlabel("Epoch")
    ax.set_ylabel("Loss")
    ax.set_title(f"梯度下降 Loss 曲線（{n_run} epochs, final={final_loss:.6f}）")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    fig.text(
        0.5,
        0.01,
        "模擬標註資料；loss 下降代表 GD 正在收斂",
        ha="center",
        fontsize=8,
        color="gray",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "gd_loss_curve.png"
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot GD training loss curve")
    parser.add_argument("--loss", type=Path, default=_DEFAULT_LOSS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    args = parser.parse_args()

    if not args.loss.is_file():
        raise SystemExit(f"找不到 loss 檔：{args.loss}（請先執行 train_risk_lr.py --solver gd）")

    _configure_matplotlib()
    path = plot_loss_curve(args.loss, args.out)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
