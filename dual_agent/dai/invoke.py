"""DAI 公開入口：簡訊審查（Defense 產 todos → Execute）或 Defense ⇄ Execute 多輪迴圈。"""

from __future__ import annotations

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL, max_defense_iterations
from dual_agent.dai.defense_execute import (
    dai_result_from_replan_final,
    dai_result_from_sms_review_plan,
    execute_defense_step,
    format_defense_observation_block,
)
from dual_agent.dai.defense_llm import invoke_defense_replan, invoke_defense_review_sms_plan
from dual_agent.dai.schemas import DAIRequest, DAIResult, DefenseObservation


def _invoke_dai_sms_review(
    req: DAIRequest,
    *,
    model: str | None,
    base_url: str | None,
    temperature: float,
) -> DAIResult:
    """
    簡訊審查固定流程：Defense 單次產出 defense_todos → Defense Execute 逐項執行 → 組裝 DAIResult。
    """
    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
    try:
        plan = invoke_defense_review_sms_plan(req, model=m, base_url=u, temperature=temperature)
    except Exception as e:  # noqa: BLE001
        return DAIResult(
            ok=False,
            risk_score=0,
            risk_labels=["plan_error"],
            safety_summary="",
            evidence=[],
            tool_restrictions={},
            recommended_cai_action="ask_user",
            defense_observations=[],
            defense_llm_turns=0,
            error=str(e),
        )
    observations: list[DefenseObservation] = []
    cap = max_defense_iterations()
    steps = list(plan.defense_todos)[:cap]
    for st in steps:
        observations.append(execute_defense_step(st, req))
    extra_defense_llm = sum(1 for st in steps if (st.skill or "").strip().lower() == "guard_scan")
    return dai_result_from_sms_review_plan(plan, observations, llm_turns=1 + extra_defense_llm)


def invoke_dai(
    req: DAIRequest,
    *,
    model: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.1,
) -> DAIResult:
    """
    DAI：
    - `sms_review=True`：Defense 先決定 `defense_todos`，再由 Execute 整批執行並回報。
    - 否則：Defense ⇄ Execute 多輪（每輪最多一個子任務或 complete）。
    """
    if req.sms_review:
        return _invoke_dai_sms_review(req, model=model, base_url=base_url, temperature=temperature)

    m = model if model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
    cap = max_defense_iterations()

    observation_lines: list[str] = []
    observations: list[DefenseObservation] = []
    llm_turns = 0

    try:
        for _ in range(cap):
            obs_log = "\n\n".join(observation_lines) if observation_lines else ""
            turn = invoke_defense_replan(
                req,
                observation_log=obs_log,
                executed_step_count=len(observations),
                model=m,
                base_url=u,
                temperature=temperature,
            )
            llm_turns += 1

            if turn.complete:
                exec_ok = all(o.ok for o in observations) if observations else True
                return dai_result_from_replan_final(
                    ok=exec_ok,
                    turn=turn,
                    observations=observations,
                    llm_turns=llm_turns,
                    error=None if exec_ok else "部分 defense 子任務執行失敗",
                )

            if turn.next_defense_step is None:
                return DAIResult(
                    ok=False,
                    risk_score=turn.risk_score,
                    risk_labels=list(turn.risk_labels),
                    safety_summary=turn.safety_summary or "（complete=false 但未提供 next_defense_step）",
                    evidence=list(turn.evidence),
                    tool_restrictions=dict(turn.tool_restrictions),
                    recommended_cai_action=turn.recommended_cai_action,
                    defense_observations=observations,
                    defense_llm_turns=llm_turns,
                    error="defense_llm_invalid: complete=false 但缺少 next_defense_step",
                )

            obs = execute_defense_step(turn.next_defense_step, req)
            observations.append(obs)
            observation_lines.append(
                format_defense_observation_block(len(observations), obs)
            )

        return DAIResult(
            ok=False,
            risk_score=0,
            risk_labels=["max_iterations"],
            safety_summary="",
            evidence=[],
            tool_restrictions={},
            recommended_cai_action="ask_user",
            defense_observations=observations,
            defense_llm_turns=llm_turns,
            error=f"已達 MAX_DEFENSE_ITERATIONS（{cap}）仍未 complete",
        )
    except Exception as e:  # noqa: BLE001
        return DAIResult(
            ok=False,
            risk_score=0,
            risk_labels=["error"],
            safety_summary="",
            evidence=[],
            tool_restrictions={},
            recommended_cai_action="ask_user",
            defense_observations=observations,
            defense_llm_turns=llm_turns,
            error=str(e),
        )
