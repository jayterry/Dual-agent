"""Memory Manager LLM 結構化輸出。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MemoryDecision(BaseModel):
    intent: Literal[
        "remember_set",
        "remember_append",
        "forget",
        "recall",
        "clarify",
        "none",
    ]
    raw_relation: str = ""
    relation: str = ""
    raw_value: str = ""
    value: str = ""
    mode: Literal["set", "append", ""] = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    answer: str = ""
    reason: str = ""
