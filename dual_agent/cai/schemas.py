"""CAI 資料結構（對齊流程圖：Planner → Executor ⇄ Replan）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dual_agent.skill_types import SkillResult


@dataclass
class PlanStep:
    skill: str
    args: dict[str, Any]


@dataclass
class PlannerOutput:
    """Planner LLM 輸出：任務型態、狀態、待辦佇列（可為空）。

    task_type 建議值：direct_response | action | check | unknown
    （direct_response：不需工具、不進 Executor，由 Replan 直接作答之任務對答；舊稱 general_qa 會正規化為此）
    """

    task_type: str
    task_state: str
    todos: list[PlanStep]
    message: str = ""


@dataclass
class ReplanOutput:
    """Replan LLM 輸出。"""

    complete: bool
    final_answer: str
    updated_todos: list[PlanStep]
    task_state: str
    waiting_input: bool = False
    user_prompt: str = ""


@dataclass
class PlanExecuteOutcome:
    plan: list[PlanStep]
    results: list[SkillResult]
    answer: str
    # task_type 與 Planner 一致：direct_response | action | check | unknown
    task_type: str = ""
    task_state: str = ""
