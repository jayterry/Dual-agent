"""CAI task_type 詞彙表（任務導向；與 open chat 區隔）。"""

from __future__ import annotations

# 對外／對模型正式枚舉（Planner JSON 應輸出其一）
ALLOWED_TASK_TYPES: tuple[str, ...] = ("direct_response", "action", "check", "unknown")

# 舊版或別名 → 正規化
_TASK_ALIASES: dict[str, str] = {
    "general_qa": "direct_response",
    "no_tool_response": "direct_response",
}


def normalize_task_type(raw: str) -> str:
    """將 LLM 輸出的 task_type 正規化為 ALLOWED_TASK_TYPES 之一。"""
    t = (raw or "").strip().lower()
    if not t:
        return "unknown"
    t = _TASK_ALIASES.get(t, t)
    if t in ALLOWED_TASK_TYPES:
        return t
    return "unknown"
