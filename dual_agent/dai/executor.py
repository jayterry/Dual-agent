"""DAI Executor：執行 dai/skills DAG。"""

from __future__ import annotations

from typing import Any

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.pipeline_context import SMS_REVIEW_DAG, DefensePipelineContext
from dual_agent.dai.schemas import DAIRequest, DefenseObservation
from dual_agent.dai.skills._pipeline_steps import STEP_HANDLERS
from dual_agent.skill_types import SkillContext, SkillResult


def build_pipeline_context(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    source: str | None = None,
    url_threat_hits_injected: list[dict[str, Any]] | None = None,
    tls_findings_injected: list[dict[str, Any]] | None = None,
) -> DefensePipelineContext:
    return DefensePipelineContext(
        req=req,
        model=model if model is not None else OLLAMA_MODEL,
        base_url=base_url if base_url is not None else OLLAMA_BASE_URL,
        temperature=temperature,
        source=(source or "desktop").strip() or "desktop",
        url_threat_hits_injected=url_threat_hits_injected,
        tls_findings_injected=tls_findings_injected,
    )


def run_dai_pipeline_step(name: str, pipe: DefensePipelineContext) -> SkillResult:
    """直接執行 DAG 步驟（不依賴 skill 資料夾載入）。"""
    fn = STEP_HANDLERS.get(name)
    if fn is None:
        return SkillResult(ok=False, skill=name, summary=f"未知 DAI 步驟：{name}", error="unknown_dai_step")
    try:
        fn(pipe)
        summary = f"{name} ok"
        if name in ("dual_path_analyze", "fuse_risk_and_ueba") and pipe.report:
            summary = str(pipe.report.get("archive_note") or summary)[:200]
            return SkillResult(
                ok=True,
                skill=name,
                summary=summary,
                data={"step": name, "report": dict(pipe.report)},
            )
        pipe.skill_trace.append({"skill": name, "ok": True, "summary": summary[:200]})
        return SkillResult(ok=True, skill=name, summary=summary, data={"step": name})
    except Exception as e:  # noqa: BLE001
        pipe.skill_trace.append({"skill": name, "ok": False, "summary": str(e)})
        return SkillResult(ok=False, skill=name, summary=f"{name} 失敗：{e}", error=str(e))


def run_sms_review_dag(
    pipe: DefensePipelineContext,
    *,
    use_skill_registry: bool = False,
    pipeline_ctx: SkillContext | None = None,
) -> tuple[dict[str, Any], list[DefenseObservation]]:
    """
    固定 DAG。use_skill_registry=True 時改走 skills_registry（測試 catalog 隔離用）。
    """
    observations: list[DefenseObservation] = []
    skill_ctx = SkillContext(
        user_input=(pipe.req.user_text or "").strip(),
        policy_state={"dai_pipeline": pipe},
    )
    for step_name in SMS_REVIEW_DAG:
        if pipeline_ctx is not None:
            from dual_agent.cai.pipeline_progress import advance_dai_step

            advance_dai_step(pipeline_ctx, step_name, model=pipe.model)
        if use_skill_registry:
            from dual_agent.skills_registry import run_dai_skill

            r = run_dai_skill(step_name, {}, skill_ctx)
        else:
            r = run_dai_pipeline_step(step_name, pipe)
        observations.append(
            DefenseObservation(
                skill=step_name,
                ok=r.ok,
                summary=r.summary[:800],
                data=dict(r.data),
            )
        )
        if not r.ok:
            break
    report = dict(pipe.report) if pipe.report else {}
    return report, observations
