"""DAI 簡訊審查 DAG 共用上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dual_agent.dai.schemas import DAIRequest

# 硬取代：主路徑改為雙路分析（舊規則／融合步驟保留於 STEP_HANDLERS，供離線 replay）
SMS_REVIEW_DAG: tuple[str, ...] = ("dual_path_analyze",)

# 舊版多步 DAG（僅供 ML feature replay／測試參考，不再由 run_sms_review_dag 執行）
LEGACY_SMS_REVIEW_DAG: tuple[str, ...] = (
    "build_analysis_payload",
    "score_rules",
    "score_threat_intel",
    "score_tls",
    "score_toxic",
    "semantic_supplement",
    "fuse_risk_and_ueba",
)


@dataclass
class DefensePipelineContext:
    req: DAIRequest
    model: str
    base_url: str
    temperature: float = 0.0
    source: str = "desktop"
    url_threat_hits_injected: list[dict[str, Any]] | None = None
    tls_findings_injected: list[dict[str, Any]] | None = None

    text: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    urls_from_text: list[str] = field(default_factory=list)
    url_threat_hits: list[dict[str, Any]] = field(default_factory=list)
    tls_findings: list[dict[str, Any]] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)

    rules_res: Any = None
    r_rules: int = 0
    r_threat_intel: int = 0
    r_tls: int = 0
    r_toxic_fused: int = 0
    toxic_meta: dict[str, Any] = field(default_factory=dict)
    ti_evidence: list[dict[str, Any]] = field(default_factory=list)
    tls_evidence: list[dict[str, Any]] = field(default_factory=list)

    component_scores: dict[str, int] = field(default_factory=dict)
    semantic: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    skill_trace: list[dict[str, Any]] = field(default_factory=list)
    # 手機／桌面進度圖用（可選）
    ui_pipeline_ctx: Any | None = None
