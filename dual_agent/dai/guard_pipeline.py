"""固定順序：Phase1 Defense 單次審查 → Phase2 Toxic + 融合 → UEBA 佔位 + 門檻 tier。"""

from __future__ import annotations

import json
import os
from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.defense_llm import invoke_defense_guard_scan
from dual_agent.dai.schemas import DAIRequest
from dual_agent.dai.toxic_chroma import match_toxic_chroma
from dual_agent.dai.toxic_fusion import ToxicMatch, fuse_risk, match_toxic
from dual_agent.dai.user_db import apply_ueba_to_report


def _text_for_pipeline(req: DAIRequest) -> str:
    art = (req.artifact or "").strip()
    if art:
        return art
    return (req.user_text or "").strip()


def _gate_tier(score_0_100: int) -> str:
    """產品門檻：<70 allow、70–84 warn、≥85 block（數值層；`verdict` 仍來自 Defense 審查 JSON，可與本欄並列決策）。"""
    if score_0_100 < 70:
        return "allow"
    if score_0_100 < 85:
        return "warn"
    return "block"


def run_guard_analysis_pipeline(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
) -> dict[str, Any]:
    """
    程式保證順序（不依 LLM 自排）：
    1) Defense 單次審查（`invoke_defense_guard_scan` → R_llm = report.risk_score_total）
    2) Toxic：TOXIC_CHROMA_PERSIST_DIR + TOXIC_CHROMA_COLLECTION 優先，否則 TOXIC_DB_PATH JSON
    3) 0.75/0.25 融合
    4) UEBA：user_db（來源 + 信任網域）
    5) gate_tier 依融合分數
    """
    text = _text_for_pipeline(req)
    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL

    report = invoke_defense_guard_scan(text=text, model=m, base_url=u, temperature=temperature)
    report_dict: dict[str, Any] = json.loads(report.to_json())

    chroma_dir = os.environ.get("TOXIC_CHROMA_PERSIST_DIR", "").strip()
    chroma_coll = os.environ.get("TOXIC_CHROMA_COLLECTION", "").strip()
    toxic_path = os.environ.get("TOXIC_DB_PATH", "").strip()

    if chroma_dir and chroma_coll:
        tm = match_toxic_chroma(
            text,
            persist_directory=chroma_dir,
            collection_name=chroma_coll,
            embed_model=m,
            base_url=u,
        )
        toxic_mode = "chroma"
    elif toxic_path:
        tm = match_toxic(raw_sms=text, toxic_path=toxic_path)
        toxic_mode = "json"
    else:
        tm = ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)
        toxic_mode = "disabled"

    fused = fuse_risk(r_llm_0_100=int(report.risk_score_total), s_tox_0_100=int(tm.s_tox_0_100))
    src = (source or "desktop").strip() or "unknown"

    report_dict["risk_fusion"] = {
        "r_llm": fused.r_llm_0_100,
        "s_tox": fused.s_tox_0_100,
        "risk_total": fused.risk_total_0_100,
        "toxic": {
            "mode": toxic_mode,
            "path": toxic_path or None,
            "chroma_dir": chroma_dir or None,
            "chroma_collection": chroma_coll or None,
            "max_cosine": tm.max_cosine,
            "best_id": tm.best_id,
            "toxic_count": tm.toxic_count,
            "embed_dim": tm.embed_dim,
        },
    }
    report_dict["risk_score_total_fused"] = fused.risk_total_0_100
    apply_ueba_to_report(report_dict, text=text, source=src)
    risk_total_user_fused = int(report_dict.get("risk_score_total_user_fused") or fused.risk_total_0_100)
    report_dict["gate_tier"] = _gate_tier(risk_total_user_fused)
    report_dict["pipeline_phases"] = [
        "defense_guard_scan",
        "toxic_match",
        "fuse_risk",
        "ueba_user_db",
        "gate_tier",
    ]

    return report_dict
