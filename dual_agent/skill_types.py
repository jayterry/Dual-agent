from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal


RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass
class SkillContext:
    """
    skills 執行時的共享上下文。

    - user_input: 使用者原始輸入（可用於 skill 自我保護 / 取證）
    - policy_state: 可跨步驟累積的狀態（風險分數、已阻擋動作、白名單…）
    - guard_result: 由 guard / policy 層產出的判斷（若有）
    - observations: skills 可追加可序列化觀察結果，供 UI/記錄使用
    """

    user_input: str
    policy_state: dict[str, Any] = field(default_factory=dict)
    guard_result: dict[str, Any] | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SkillResult:
    ok: bool
    skill: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    risk_delta: int = 0
    blocked_actions: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    error: str | None = None


SkillHandler = Callable[[dict[str, Any], SkillContext], SkillResult]


@dataclass
class SkillSpec:
    name: str
    description: str
    handler: SkillHandler
    aliases: list[str] = field(default_factory=list)
    risk_level: RiskLevel = "low"
    requires_confirmation: bool = False
    args_schema: dict[str, Any] = field(default_factory=dict)
    skill_dir: str | None = None

