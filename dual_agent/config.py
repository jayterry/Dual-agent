"""環境設定（本機 Ollama／迴圈上限等預設值）。"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b")


def max_replan_iterations() -> int:
    raw = _env("MAX_REPLAN_ITERATIONS", "5")
    try:
        n = int(raw)
    except ValueError:
        return 5
    return max(1, min(50, n))


def max_executor_steps() -> int:
    """單一使用者回合內，Executor 最多執行幾次 Todo[0]（避免重複開網頁／搜尋）。"""
    raw = _env("MAX_EXECUTOR_STEPS", "3")
    try:
        n = int(raw)
    except ValueError:
        return 3
    return max(1, min(20, n))


def max_defense_iterations() -> int:
    """單次 invoke_dai：Defense LLM ⇄ Execute 迴圈上限（與 CAI MAX_REPLAN_ITERATIONS 概念對齊）。"""
    raw = _env("MAX_DEFENSE_ITERATIONS", "8")
    try:
        n = int(raw)
    except ValueError:
        return 8
    return max(1, min(32, n))


def context_buffer_max_rounds() -> int:
    """Memory / Context Layer：最近對話緩衝最多保留幾輪；超過則壓入 rolling_summary。"""
    raw = _env("CONTEXT_BUFFER_MAX_ROUNDS", "10")
    try:
        n = int(raw)
    except ValueError:
        return 10
    return max(2, min(50, n))
