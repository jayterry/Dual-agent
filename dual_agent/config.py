"""環境設定（本機 Ollama／迴圈上限等預設值）。"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v.strip() if isinstance(v, str) and v.strip() else default


OLLAMA_BASE_URL = _env("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = _env("OLLAMA_MODEL", "qwen2.5:7b")


def cai_memory_model() -> str:
    """
    CAI Memory Manager LLM（語意 intent／關係／姓名）。
    預設與 OLLAMA_MODEL 相同，避免本機未 pull 3b 時 404；
    可設 CAI_MEMORY_MODEL=qwen2.5:3b 等較小模型以降延遲。
    """
    return _env("CAI_MEMORY_MODEL", OLLAMA_MODEL)


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


def dai_risk_llm_weight() -> float:
    """DAI 風險融合：語意層（R-LLM）權重，其餘為機器層（硬規則／情資／TLS／毒樣）。"""
    raw = _env("DAI_R_LLM_WEIGHT", "0.35")
    try:
        w = float(raw)
    except ValueError:
        return 0.35
    return max(0.0, min(1.0, w))


def memory_confidence_min() -> float:
    """Memory Manager：寫入前最低 confidence（預設 0.65）。"""
    raw = _env("MEMORY_CONFIDENCE_MIN", "0.65")
    try:
        v = float(raw)
    except ValueError:
        return 0.65
    return max(0.0, min(1.0, v))


def context_buffer_max_rounds() -> int:
    """Memory / Context Layer：最近對話緩衝最多保留幾輪；超過則壓入 rolling_summary。"""
    raw = _env("CONTEXT_BUFFER_MAX_ROUNDS", "10")
    try:
        n = int(raw)
    except ValueError:
        return 10
    return max(2, min(50, n))
