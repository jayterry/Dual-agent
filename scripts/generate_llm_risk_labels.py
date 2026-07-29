#!/usr/bin/env python3
"""以 LLM（或模板擴寫）產生銀行面風險標註 Dataset。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.risk_analysis.ml.labels import write_labels_jsonl
from dual_agent.dai.risk_analysis.ml.llm_synth import generate_bank_corpus

_DEFAULT_OUT = _ROOT / "data" / "risk_training" / "labels_llm_bank_600.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bank-domain synthetic risk labels")
    parser.add_argument("--domain", default="bank", choices=["bank"], help="資料領域（本輪僅 bank）")
    parser.add_argument("--n-scam", type=int, default=300)
    parser.add_argument("--n-benign", type=int, default=300)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument("--model", default=OLLAMA_MODEL)
    parser.add_argument("--base-url", default=OLLAMA_BASE_URL)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--fallback-templates",
        action="store_true",
        help="不呼叫 LLM，僅用銀行模板槽位擴寫（離線／smoke）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只產生少量樣本驗證管線（各 6 筆）",
    )
    args = parser.parse_args()

    n_scam = 6 if args.dry_run else args.n_scam
    n_benign = 6 if args.dry_run else args.n_benign
    use_llm = not args.fallback_templates

    print(
        f"domain={args.domain} n_scam={n_scam} n_benign={n_benign} "
        f"use_llm={use_llm} model={args.model}"
    )
    records = generate_bank_corpus(
        n_scam=n_scam,
        n_benign=n_benign,
        model=args.model,
        base_url=args.base_url,
        batch_size=args.batch_size,
        seed=args.seed,
        use_llm=use_llm,
    )
    write_labels_jsonl(args.out, records)
    scam_n = sum(1 for r in records if r.label == "scam")
    benign_n = sum(1 for r in records if r.label == "benign")
    buckets = sorted({r.notes for r in records})
    print(
        f"Wrote {len(records)} rows to {args.out} "
        f"(scam={scam_n}, benign={benign_n}, buckets={buckets})"
    )
    if len(records) != n_scam + n_benign:
        print(
            f"WARNING: expected {n_scam + n_benign}, got {len(records)}",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
