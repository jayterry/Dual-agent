"""訓練 HeteroGNN Context Scorer。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import GroupShuffleSplit
from torch.optim import Adam

from dual_agent.dai.fraud_dual.gnn.hetero_model import (
    DEFAULT_HETERO_PATH,
    HeteroContextNet,
    infer_in_dims,
    sample_to_hetero,
)
from dual_agent.dai.fraud_dual.ml.dataset import load_context_samples

DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[2] / "models"


def train_hetero(
    *,
    epochs: int = 8,
    batch_size: int = 64,
    lr: float = 1e-3,
    random_state: int = 42,
    max_train: int | None = None,
) -> Path:
    samples = load_context_samples()
    groups = np.array([s.text for s in samples])
    y = np.asarray([s.context_score for s in samples], dtype=float)
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=random_state)
    train_idx, test_idx = next(gss.split(np.arange(len(samples)), y, groups))
    train_s = [samples[i] for i in train_idx]
    test_s = [samples[i] for i in test_idx]
    if max_train is not None:
        train_s = train_s[:max_train]

    print(f"Building graphs train={len(train_s)} test={len(test_s)} ...")
    train_graphs = [sample_to_hetero(s) for s in train_s]
    test_graphs = [sample_to_hetero(s) for s in test_s]

    device = torch.device("cpu")
    model = HeteroContextNet(infer_in_dims(), hidden=64).to(device)
    opt = Adam(model.parameters(), lr=lr)

    def _run_epoch(graphs, train: bool) -> float:
        model.train(train)
        total = 0.0
        n = 0
        order = list(range(len(graphs)))
        if train:
            rng = np.random.default_rng(random_state + n + len(graphs))
            rng.shuffle(order)
        for start in range(0, len(order), batch_size):
            batch_ids = order[start : start + batch_size]
            losses = []
            for j in batch_ids:
                data = graphs[j].to(device)
                pred = model(data.x_dict, data.edge_index_dict)
                loss = torch.nn.functional.mse_loss(pred, data.y)
                losses.append(loss)
            if not losses:
                continue
            loss_b = torch.stack(losses).mean()
            if train:
                opt.zero_grad()
                loss_b.backward()
                opt.step()
            total += float(loss_b.detach()) * len(batch_ids)
            n += len(batch_ids)
        return total / max(n, 1)

    history = []
    for ep in range(1, epochs + 1):
        tr = _run_epoch(train_graphs, True)
        history.append({"epoch": ep, "train_mse": tr})
        print(f"epoch {ep}/{epochs} train_mse={tr:.6f}")

    # eval
    model.eval()
    preds, golds = [], []
    with torch.no_grad():
        for data, s in zip(test_graphs, test_s):
            data = data.to(device)
            p = float(model(data.x_dict, data.edge_index_dict).cpu().numpy()[0])
            preds.append(p)
            golds.append(s.context_score)
    preds_a = np.clip(np.asarray(preds), 0, 1)
    golds_a = np.asarray(golds)
    metrics = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "backend": "hetero_sage_v1",
        "n_train": len(train_s),
        "n_test": len(test_s),
        "epochs": epochs,
        "mae": float(mean_absolute_error(golds_a, preds_a)),
        "r2": float(r2_score(golds_a, preds_a)),
        "history": history,
        "note": "Teacher labels rules_v1; split grouped by message content.",
    }

    out = DEFAULT_MODEL_DIR / "context_hetero.pt"
    DEFAULT_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "in_dims": infer_in_dims(),
            "hidden": 64,
            "metrics": metrics,
            "version": "hetero_sage_v1",
        },
        out,
    )
    (DEFAULT_MODEL_DIR / "context_hetero_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out
