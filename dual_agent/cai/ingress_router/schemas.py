"""L1 Ingress Intent Router 結構化輸出。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngressRouteDecision(BaseModel):
    task_type: Literal[
        "action",
        "check",
        "direct_response",
        "memory_update",
        "unknown",
    ]
    requires_dai: bool = False
    artifact_role: Literal["none", "artifact", "pending_review"] = "none"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
