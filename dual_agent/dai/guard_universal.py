"""向後相容：DAI 內唯一 LLM 為 Defense；單次審查請用 `defense_llm.invoke_defense_guard_scan`。"""

from __future__ import annotations

from dual_agent.dai.defense_llm import (
    GuardExtracted,
    GuardReport,
    GuardSignal,
    _normalize_verdict,
    invoke_defense_guard_scan,
    run_guard_universal,
)

__all__ = [
    "GuardExtracted",
    "GuardReport",
    "GuardSignal",
    "invoke_defense_guard_scan",
    "run_guard_universal",
    "_normalize_verdict",
]
