"""Hybrid：多技能執行結果合併為 Replan observation 區塊。"""

from __future__ import annotations

from dual_agent.cai.schemas import PlanStep
from dual_agent.skill_types import SkillResult


def format_observation_block(lines: list[str]) -> str:
    joined = "\n\n".join((ln or "").strip() for ln in lines if (ln or "").strip())
    return joined or "（尚無執行結果）"


def fuse_skill_results_for_replan(
    *,
    executed: list[PlanStep],
    results: list[SkillResult],
    display_blocks: list[str],
) -> str:
    """將已執行步驟與格式化結果合併為 observation_log。"""
    lines: list[str] = []
    for i, block in enumerate(display_blocks):
        skill = executed[i].skill if i < len(executed) else "unknown"
        lines.append(f"--- 第 {i + 1} 次執行：{skill} ---\n{block}")
    return format_observation_block(lines)
