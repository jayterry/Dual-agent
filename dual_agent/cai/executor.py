from __future__ import annotations

from dual_agent.cai.schemas import PlanStep
from dual_agent.skill_types import SkillContext, SkillResult
from dual_agent.skills_registry import SKILLS, _resolve_skill_name, run_skill

_CAI_DAI_BRIDGE = frozenset({"call_dai"})


def execute_step(step: PlanStep, ctx: SkillContext) -> SkillResult:
    key = _resolve_skill_name(step.skill)
    if key is None:
        return run_skill(step.skill, step.args, ctx)
    spec = SKILLS[key]
    if spec.agent == "dai" and step.skill not in _CAI_DAI_BRIDGE:
        return SkillResult(
            ok=False,
            skill=step.skill,
            summary=f"CAI Executor 不可直接執行 DAI 技能 {step.skill!r}，請使用 call_dai",
            error="cai_cannot_run_dai_skill",
        )
    return run_skill(step.skill, step.args, ctx)


def execute_plan(steps: list[PlanStep], ctx: SkillContext) -> list[SkillResult]:
    return [execute_step(st, ctx) for st in steps]


def _tool_observation_excerpt(r: SkillResult) -> str:
    """將需供 Replan 閱讀的正文附在觀測紀錄（fetch_url 等）。"""
    if not r.ok or not r.data:
        return ""
    if r.skill == "fetch_url":
        text = r.data.get("text")
        if not text:
            return ""
        s = str(text)
        cap = 20_000
        if len(s) > cap:
            s = s[:cap] + "\n…（觀測紀錄截斷）"
        return f"（抓取正文）\n{s}"
    if r.skill == "call_dai":
        dai = r.data.get("dai")
        if not isinstance(dai, dict):
            return ""
        display = str(dai.get("display_text") or "").strip()
        if display:
            return f"（DAI 詳細結果）\n{display}"
        lines = ["（DAI 詳細結果）"]
        score = dai.get("risk_score")
        if isinstance(score, (int, float)):
            lines.append(f"風險分數：{int(score)}/100")
        verdict = str(dai.get("verdict") or "").strip()
        if verdict:
            lines.append(f"判定：{verdict}")
        action = str(dai.get("recommended_cai_action") or "").strip()
        if action:
            lines.append(f"建議動作：{action}")
        reasons = dai.get("user_reason_highlights") or dai.get("reason_highlights") or []
        if isinstance(reasons, list):
            picked = [str(x).strip()[:160] for x in reasons if str(x).strip()][:5]
            if picked:
                lines.append("主要原因：")
                lines.extend(f"- {x}" for x in picked)
        suggestions = dai.get("user_suggestions") or []
        if isinstance(suggestions, list):
            picked_s = [str(x).strip()[:160] for x in suggestions if str(x).strip()][:5]
            if picked_s:
                lines.append("建議：")
                lines.extend(f"- {x}" for x in picked_s)
        return "\n".join(lines)
    return ""


def format_results_for_display(results: list[SkillResult]) -> str:
    lines: list[str] = []
    for r in results:
        mark = "OK" if r.ok else "FAIL"
        lines.append(f"[{mark}] {r.skill}: {r.summary}")
        extra = _tool_observation_excerpt(r)
        if extra:
            lines.append(extra)
    return "\n".join(lines)

