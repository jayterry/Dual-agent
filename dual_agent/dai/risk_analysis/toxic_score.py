"""Toxic DB → r_toxic_fused（0–100）。"""

from __future__ import annotations

import os
from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.toxic_chroma import match_toxic_chroma
from dual_agent.dai.toxic_fusion import ToxicMatch, match_toxic


def compute_r_toxic_fused(
    text: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> tuple[int, dict[str, Any]]:
    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
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
        mode = "chroma"
    elif toxic_path:
        tm = match_toxic(raw_sms=text, toxic_path=toxic_path)
        mode = "json"
    else:
        tm = ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)
        mode = "disabled"

    meta = {
        "mode": mode,
        "s_tox": int(tm.s_tox_0_100),
        "max_cosine": tm.max_cosine,
        "best_id": tm.best_id,
        "toxic_count": tm.toxic_count,
    }
    return int(tm.s_tox_0_100), meta
