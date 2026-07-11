#!/usr/bin/env python3
"""已改為問題導向審計；此腳本轉呼叫 run_problem_reports_audit。"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.run_problem_reports_audit import main

if __name__ == "__main__":
    raise SystemExit(main())
