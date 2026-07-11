"""離線重播 DAI DAG（至 semantic_supplement），供特徵匯出。"""

from __future__ import annotations

import os
from typing import Any

from dual_agent.dai.executor import build_pipeline_context
from dual_agent.dai.pipeline_context import SMS_REVIEW_DAG
from dual_agent.dai.schemas import DAIRequest
from dual_agent.dai.skills._pipeline_steps import STEP_HANDLERS

FEATURE_DAG_STEPS: tuple[str, ...] = tuple(s for s in SMS_REVIEW_DAG if s != "fuse_risk_and_ueba")


def replay_feature_context(
    text: str,
    *,
    source: str = "seed",
    with_semantic: bool = True,
    url_threat_hits_injected: list[dict[str, Any]] | None = None,
    tls_findings_injected: list[dict[str, Any]] | None = None,
) -> Any:
    """
    跑 build → rules → TI → TLS → toxic →（可選）semantic，回傳 DefensePipelineContext。
    """
    req = DAIRequest(
        user_text=text,
        artifact=text,
        sms_review=True,
        source=source,
    )
    pipe = build_pipeline_context(
        req,
        source=source,
        url_threat_hits_injected=url_threat_hits_injected,
        tls_findings_injected=tls_findings_injected,
    )
    prev_semantic = os.environ.get("DAI_SEMANTIC_LLM")
    if not with_semantic:
        os.environ["DAI_SEMANTIC_LLM"] = "0"
    try:
        for step in FEATURE_DAG_STEPS:
            fn = STEP_HANDLERS.get(step)
            if fn is None:
                raise RuntimeError(f"unknown step: {step}")
            fn(pipe)
    finally:
        if not with_semantic:
            if prev_semantic is None:
                os.environ.pop("DAI_SEMANTIC_LLM", None)
            else:
                os.environ["DAI_SEMANTIC_LLM"] = prev_semantic
    return pipe
