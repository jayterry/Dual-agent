#!/usr/bin/env python3
"""產生模擬標註 labels.jsonl（規則觸發句 + benign 模板）。"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.dai.risk_analysis.ml.labels import LabelRecord, write_labels_jsonl
from dual_agent.dai.risk_analysis.ml.synthetic_corpus import BENIGN_TEMPLATES, SCAM_TEMPLATES

_DEFAULT_OUT = _ROOT / "data" / "risk_training" / "labels_synthetic.jsonl"


def _verdict_for_scam(text: str) -> str:
    high = ("密碼", "匯款", "驗證碼", "卡號", "轉帳", "CVV", "PIN", "身分證")
    if any(k in text for k in high):
        return "block"
    return "warn"


def _assign_stratified_splits(records: list[LabelRecord], *, seed: int = 42) -> None:
    """依 label 分層切分 train/val/test（70/15/15）。"""
    rng = random.Random(seed)
    by_label: dict[str, list[LabelRecord]] = {"scam": [], "benign": []}
    for rec in records:
        by_label[rec.label].append(rec)

    for group in by_label.values():
        rng.shuffle(group)
        n = len(group)
        n_train = int(n * 0.7)
        n_val = int(n * 0.15)
        for i, rec in enumerate(group):
            if i < n_train:
                rec.split = "train"  # type: ignore[misc]
            elif i < n_train + n_val:
                rec.split = "val"  # type: ignore[misc]
            else:
                rec.split = "test"  # type: ignore[misc]


def build_synthetic_records(*, seed: int = 42) -> list[LabelRecord]:
    records: list[LabelRecord] = []

    for text, note in SCAM_TEMPLATES:
        records.append(
            LabelRecord(
                id=str(uuid.uuid4()),
                text=text,
                source="synthetic",
                label="scam",
                verdict_gt=_verdict_for_scam(text),
                annotator="synthetic_corpus_v2",
                split="train",
                notes=note,
            )
        )

    for text, note in BENIGN_TEMPLATES:
        records.append(
            LabelRecord(
                id=str(uuid.uuid4()),
                text=text,
                source="synthetic",
                label="benign",
                verdict_gt="allow",
                annotator="synthetic_corpus_v2",
                split="train",
                notes=note,
            )
        )

    _assign_stratified_splits(records, seed=seed)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap synthetic risk labels")
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="輸出 JSONL 路徑",
    )
    parser.add_argument("--seed", type=int, default=42, help="分層切分隨機種子")
    args = parser.parse_args()
    records = build_synthetic_records(seed=args.seed)
    write_labels_jsonl(args.out, records)
    scam_n = sum(1 for r in records if r.label == "scam")
    benign_n = sum(1 for r in records if r.label == "benign")
    train_n = sum(1 for r in records if r.split == "train")
    val_n = sum(1 for r in records if r.split == "val")
    test_n = sum(1 for r in records if r.split == "test")
    print(
        f"Wrote {len(records)} rows to {args.out} "
        f"(scam={scam_n}, benign={benign_n}, train={train_n}, val={val_n}, test={test_n})"
    )


if __name__ == "__main__":
    main()
