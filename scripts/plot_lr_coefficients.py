#!/usr/bin/env python3
"""繪製 LR 係數（特徵重要性）長條圖。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _configure_matplotlib() -> None:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for name in ("Microsoft JhengHei", "Microsoft YaHei", "SimHei", "Noto Sans CJK TC"):
        if name in {f.name for f in font_manager.fontManager.ttflist}:
            plt.rcParams["font.sans-serif"] = [name, *plt.rcParams["font.sans-serif"]]
            break
    plt.rcParams["axes.unicode_minus"] = False


def plot_top_coefficients(coef_path: Path, out_dir: Path, *, top_k: int = 20) -> Path:
    import matplotlib.pyplot as plt

    data = json.loads(coef_path.read_text(encoding="utf-8"))
    top = data.get("top_abs_15") or []
    if not top:
        coefs = data.get("coefficients") or {}
        top = sorted(coefs.items(), key=lambda kv: abs(float(kv[1])), reverse=True)[:top_k]
    else:
        top = top[:top_k]

    if not top:
        raise SystemExit(f"無係數可繪：{coef_path}")

    names = [str(n) for n, _ in reversed(top)]
    values = [float(v) for _, v in reversed(top)]
    colors = ["#d62728" if v > 0 else "#1f77b4" for v in values]

    fig, ax = plt.subplots(figsize=(10, max(5, len(names) * 0.35)))
    ax.barh(names, values, color=colors)
    ax.axvline(0, color="gray", linewidth=0.8)
    ax.set_xlabel("係數（正＝提高 scam 機率）")
    ax.set_title(f"LR 特徵係數 Top {len(names)}（紅=拉高風險／藍=拉低風險）")
    ax.grid(True, axis="x", alpha=0.3)
    fig.text(
        0.5,
        0.01,
        "銀行面合成資料訓練；係數供解釋用，非正式因果推論",
        ha="center",
        fontsize=8,
        color="gray",
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "lr_coefficients_top.png"
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Plot LR coefficient bar chart")
    parser.add_argument(
        "--coefficients",
        type=Path,
        default=_ROOT / "data" / "risk_models" / "lr_bank_v0_gd" / "coefficients.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "data" / "risk_models" / "lr_bank_v0_gd" / "eval_plots",
    )
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    if not args.coefficients.is_file():
        raise SystemExit(f"找不到係數檔：{args.coefficients}")

    try:
        import matplotlib  # noqa: F401
    except ImportError as e:
        raise SystemExit("請安裝 matplotlib：pip install matplotlib") from e

    _configure_matplotlib()
    path = plot_top_coefficients(args.coefficients, args.out, top_k=args.top_k)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
