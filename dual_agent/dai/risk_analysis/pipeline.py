"""run_risk_analysis：薄包裝，委派 DAI Executor 固定 DAG。"""

from __future__ import annotations

from typing import Any

from dual_agent.dai.executor import build_pipeline_context, run_sms_review_dag
from dual_agent.dai.risk_analysis.summary import coherent_safety_summary
from dual_agent.dai.schemas import DAIRequest

# 向後相容測試匯入
_coherent_safety_summary = coherent_safety_summary


def run_risk_analysis(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
    url_threat_hits_injected: list[dict[str, Any]] | None = None,
    tls_findings_injected: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pipe = build_pipeline_context(
        req,
        model=model,
        base_url=base_url,
        temperature=temperature,
        source=source,
        url_threat_hits_injected=url_threat_hits_injected,
        tls_findings_injected=tls_findings_injected,
    )
    report, _ = run_sms_review_dag(pipe)
    return report
