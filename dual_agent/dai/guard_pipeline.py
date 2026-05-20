"""固定順序：機器分項 → max 合成 → 語意 H/I → UEBA → gate_tier。"""

from __future__ import annotations

from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
from dual_agent.dai.schemas import DAIRequest

def run_guard_analysis_pipeline(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
) -> dict[str, Any]:
    """向後相容入口：委派至 run_risk_analysis。"""
    return run_risk_analysis(
        req,
        model=model,
        base_url=base_url,
        temperature=temperature,
        source=source,
    )


def run_risk_analysis_legacy_alias(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
) -> dict[str, Any]:
    return run_risk_analysis(
        req,
        model=model,
        base_url=base_url,
        temperature=temperature,
        source=source,
    )
