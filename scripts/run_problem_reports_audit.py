#!/usr/bin/env python3
"""依 test_reports/*/scenarios.json 執行問題導向審計（不需 Ollama）。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.problem_report_runner import run_all


def main() -> int:
    print("執行問題導向審計（讀取 test_reports/*/scenarios.json）…")
    code, results = run_all()
    for result in results:
        if result.findings or result.report_dir.joinpath("scenarios.json").exists():
            print(f"結果已寫入 {result.report_dir / 'audit_latest.json'}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
