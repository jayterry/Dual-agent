from __future__ import annotations

from dual_agent.cai.schemas import PlanStep
from dual_agent.skill_types import SkillContext, SkillResult
from dual_agent.skills_registry import run_skill


def execute_step(step: PlanStep, ctx: SkillContext) -> SkillResult:
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
        lines = ["（DAI 詳細結果）"]
        score = dai.get("risk_score")
        if isinstance(score, (int, float)):
            lines.append(f"風險分數：{int(score)}/100")
        action = str(dai.get("recommended_cai_action") or "").strip()
        if action:
            lines.append(f"建議動作：{action}")
        summary = str(dai.get("safety_summary") or "").strip()
        if summary:
            lines.append(f"摘要：{summary[:300]}")
        reasons = dai.get("reason_highlights") or []
        if isinstance(reasons, list):
            picked = [str(x).strip()[:160] for x in reasons if str(x).strip()][:3]
            if picked:
                lines.append("主要原因：")
                lines.extend(f"- {x}" for x in picked)
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

