#!/usr/bin/env python3
"""對標註語料重播 DAG 並匯出特徵（CSV/JSONL）。"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.dai.risk_analysis.ml.feature_extractor import features_from_pipeline_context
from dual_agent.dai.risk_analysis.ml.labels import load_labels_jsonl
from dual_agent.dai.risk_analysis.ml.pipeline_replay import replay_feature_context
from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.schemas import DAIRequest

_DEFAULT_LABELS = _ROOT / "data" / "risk_training" / "labels_synthetic.jsonl"
_DEFAULT_OUT = _ROOT / "data" / "risk_training" / "features_synthetic.csv"


def _legacy_risk_score(text: str) -> int:
    prev = os.environ.get("DAI_SEMANTIC_LLM")
    os.environ["DAI_SEMANTIC_LLM"] = "0"
    try:
        report = run_risk_analysis(
            DAIRequest(user_text=text, artifact=text, sms_review=True, source="seed"),
        )
        return int(report.get("risk_score") or 0)
    finally:
        if prev is None:
            os.environ.pop("DAI_SEMANTIC_LLM", None)
        else:
            os.environ["DAI_SEMANTIC_LLM"] = prev


def export_features(
    labels_path: Path,
    out_path: Path,
    *,
    with_semantic: bool = False,
    include_legacy: bool = True,
) -> int:
    records = load_labels_jsonl(labels_path)
    rows: list[dict[str, object]] = []

    for rec in records:
        if not rec.text:
            continue
        pipe = replay_feature_context(
            rec.text,
            source=rec.source or "seed",
            with_semantic=with_semantic,
        )
        fv = features_from_pipeline_context(pipe)
        row: dict[str, object] = {
            "id": rec.id,
            "label": rec.label,
            "split": rec.split,
            "text": rec.text,
            "y_scam": 1 if rec.label == "scam" else 0,
        }
        if include_legacy:
            row["legacy_risk_score"] = _legacy_risk_score(rec.text)
        row.update(fv.to_dict())
        rows.append(row)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".jsonl":
        with out_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    else:
        if not rows:
            out_path.write_text("", encoding="utf-8")
            return 0
        fieldnames = list(rows[0].keys())
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ML risk features from labels JSONL")
    parser.add_argument("--labels", type=Path, default=_DEFAULT_LABELS)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument(
        "--with-semantic",
        action="store_true",
        help="啟用 semantic_supplement（需 Ollama）",
    )
    parser.add_argument("--no-legacy", action="store_true", help="不計算 legacy_risk_score")
    args = parser.parse_args()
    n = export_features(
        args.labels,
        args.out,
        with_semantic=args.with_semantic,
        include_legacy=not args.no_legacy,
    )
    print(f"Exported {n} feature rows to {args.out}")


if __name__ == "__main__":
    main()
