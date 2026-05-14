"""Defense Execute：執行 Defense 排定之子步驟；並格式化觀測供後續輪次使用。"""

from __future__ import annotations

import json
from typing import Any, Callable

from dual_agent.dai.defense_llm import invoke_defense_guard_scan

from dual_agent.dai.schemas import (
    DAIRequest,
    DAIResult,
    DefenseObservation,
    DefensePlan,
    DefenseReplanOutput,
    DefenseStep,
)

# 舊版「一次跑完多個 defense_todos」上限（僅 run_defense_execute_legacy 使用）
_MAX_DEFENSE_STEPS_LEGACY = 8


def _step_noop(_args: dict[str, Any], _req: DAIRequest) -> DefenseObservation:
    return DefenseObservation(skill="noop", ok=True, summary="noop", data={})


def _step_guard_scan(_args: dict[str, Any], req: DAIRequest) -> DefenseObservation:
    """對 artifact／user_text 跑 Defense 單次結構化審查（invoke_defense_guard_scan）。"""
    text = (req.artifact or "").strip() or (req.user_text or "").strip()
    if not text:
        return DefenseObservation(
            skill="guard_scan",
            ok=False,
            summary="無待審文字",
            data={"error": "empty_input"},
        )
    report = invoke_defense_guard_scan(text=text)
    d: dict[str, Any] = json.loads(report.to_json())
    note = str(d.get("archive_note") or "").strip()
    sm = str(d.get("sanitized_memory") or "").strip()
    summary = (note or sm or "guard_scan 完成")[:800]
    return DefenseObservation(skill="guard_scan", ok=True, summary=summary, data=d)


DEFENSE_STEP_REGISTRY: dict[str, Callable[[dict[str, Any], DAIRequest], DefenseObservation]] = {
    "guard_scan": _step_guard_scan,
    "noop": _step_noop,
}


def format_defense_observation_block(step_index: int, obs: DefenseObservation) -> str:
    """供 Defense LLM 下一輪閱讀的單段紀錄。"""
    mark = "OK" if obs.ok else "FAIL"
    return f"--- defense 第 {step_index} 次執行：{obs.skill} ---\n[{mark}] {obs.skill}: {obs.summary}"


def execute_defense_step(step: DefenseStep, req: DAIRequest) -> DefenseObservation:
    key = (step.skill or "").strip().lower()
    fn = DEFENSE_STEP_REGISTRY.get(key)
    if fn is None:
        return DefenseObservation(
            skill=step.skill,
            ok=False,
            summary=f"不支援的 defense skill：{step.skill!r}",
            data={"error": "unknown_defense_skill"},
        )
    try:
        return fn(dict(step.args), req)
    except Exception as e:  # noqa: BLE001
        return DefenseObservation(
            skill=step.skill,
            ok=False,
            summary=f"執行異常：{e}",
            data={},
        )


def run_defense_execute_legacy(plan: DefensePlan, req: DAIRequest) -> DAIResult:
    """
    舊版：一次執行 plan 內多個 defense_todos（測試／相容用）。
    """
    observations: list[DefenseObservation] = []
    steps = list(plan.defense_todos)[:_MAX_DEFENSE_STEPS_LEGACY]
    all_ok = True
    for st in steps:
        obs = execute_defense_step(st, req)
        observations.append(obs)
        if not obs.ok:
            all_ok = False

    return DAIResult(
        ok=all_ok,
        risk_score=plan.risk_score,
        risk_labels=list(plan.risk_labels),
        safety_summary=plan.safety_summary,
        evidence=list(plan.evidence),
        tool_restrictions=dict(plan.tool_restrictions),
        recommended_cai_action=plan.recommended_cai_action,
        defense_observations=observations,
        defense_llm_turns=0,
        error=None if all_ok else "部分 defense_todos 執行失敗",
    )


def dai_result_from_sms_review_plan(
    plan: DefensePlan,
    observations: list[DefenseObservation],
    *,
    llm_turns: int = 1,
    error: str | None = None,
) -> DAIResult:
    """簡訊審查：Defense 已產計畫、Execute 已跑完，組裝最終 DAIResult。"""
    exec_ok = all(o.ok for o in observations) if observations else True
    max_r = int(plan.risk_score)
    extra_evidence: list[dict[str, Any]] = list(plan.evidence)
    for o in observations:
        if o.skill == "guard_scan" and isinstance(o.data, dict):
            rt = o.data.get("risk_score_total")
            if isinstance(rt, (int, float)):
                max_r = max(max_r, int(rt))
            extra_evidence.append({"source": "guard_scan", "verdict": o.data.get("verdict")})
    safety = (plan.safety_summary or "").strip()
    if not safety and observations:
        parts = [o.summary for o in observations if (o.summary or "").strip()]
        safety = " | ".join(parts)[:2000]
    if not safety:
        safety = "簡訊審查已完成。" if exec_ok else "簡訊審查執行未完成。"
    return DAIResult(
        ok=exec_ok,
        risk_score=max_r,
        risk_labels=list(plan.risk_labels),
        safety_summary=safety,
        evidence=extra_evidence,
        tool_restrictions=dict(plan.tool_restrictions),
        recommended_cai_action=plan.recommended_cai_action,
        defense_observations=list(observations),
        defense_llm_turns=llm_turns,
        error=error,
    )


def dai_result_from_replan_final(
    *,
    ok: bool,
    turn: DefenseReplanOutput,
    observations: list[DefenseObservation],
    llm_turns: int,
    error: str | None = None,
) -> DAIResult:
    """由最後一次 complete 的 DefenseReplanOutput 組裝 DAIResult。"""
    return DAIResult(
        ok=ok,
        risk_score=turn.risk_score,
        risk_labels=list(turn.risk_labels),
        safety_summary=turn.safety_summary,
        evidence=list(turn.evidence),
        tool_restrictions=dict(turn.tool_restrictions),
        recommended_cai_action=turn.recommended_cai_action,
        defense_observations=list(observations),
        defense_llm_turns=llm_turns,
        error=error,
    )
