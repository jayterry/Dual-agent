"""Hybrid system prompts 與 few-shot 資源。"""

from __future__ import annotations

import json
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt(name: str) -> str:
    """讀取 prompts 目錄下的 .txt（如 nlp_system、planner_system、react_replan）。"""
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def load_fewshots(filename: str) -> dict:
    path = _PROMPTS_DIR / "fewshots" / filename
    return json.loads(path.read_text(encoding="utf-8"))
