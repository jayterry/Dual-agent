"""產生 DAI pipeline skill 的 handle()。"""

from __future__ import annotations

from typing import Any, Callable

from dual_agent.dai.pipeline_context import DefensePipelineContext
from dual_agent.dai.skills._pipeline_steps import STEP_HANDLERS
from dual_agent.skill_types import SkillContext, SkillResult


def make_dai_step_handler(step_name: str) -> Callable[[dict[str, Any], SkillContext], SkillResult]:
    fn = STEP_HANDLERS[step_name]

    def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
        pipe = ctx.policy_state.get("dai_pipeline")
        if not isinstance(pipe, DefensePipelineContext):
            return SkillResult(
                ok=False,
                skill=step_name,
                summary="缺少 dai_pipeline 上下文",
                error="no_dai_pipeline",
            )
        try:
            fn(pipe)
            if step_name == "fuse_risk_and_ueba":
                rs = int((pipe.report or {}).get("risk_score") or 0)
                return SkillResult(
                    ok=True,
                    skill=step_name,
                    summary=f"risk_score={rs}",
                    data={"report": pipe.report},
                )
            if step_name == "score_rules":
                return SkillResult(ok=True, skill=step_name, summary=f"r_rules={pipe.r_rules}")
            return SkillResult(ok=True, skill=step_name, summary=f"{step_name} ok")
        except Exception as e:  # noqa: BLE001
            return SkillResult(ok=False, skill=step_name, summary=str(e), error=str(e))

    return handle
