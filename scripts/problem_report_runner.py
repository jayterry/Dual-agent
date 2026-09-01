"""依 test_reports/<問題>/scenarios.json 執行問題導向審計（不需 Ollama）。"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.review_entry_eligibility import looks_like_review_intent_without_artifact
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.cai.semantic_router import apply_semantic_router, route_user_text
from dual_agent.cai.context_layer import normalize_user_facts
from dual_agent.cai.memory_direct import try_handle_memory_turn
from dual_agent.ingress import normalize_ingress
from dual_agent.skill_types import SkillContext, SkillResult

_BANK_SCAM_BODY = "【XX銀行】您的帳戶異常，請點擊 https://fake-bank.com 完成驗證"

_EXECUTE_MOCKS: dict[str, Any] = {
    "call_dai_success": lambda step, _ctx: SkillResult(
        ok=True,
        skill="call_dai",
        summary="[DAI] 風險分數 75/100",
        data={
            "dai": {
                "risk_score": 75,
                "recommended_cai_action": "warn",
                "display_text": "風險分數：75/100\n判定：warn",
                "safety_summary": "疑似釣魚",
            }
        },
    ),
    "noop_ok": lambda step, _ctx: SkillResult(
        ok=True,
        skill=str(getattr(step, "skill", "unknown")),
        summary=f"ok {getattr(step, 'skill', '')}",
    ),
}


@dataclass
class Finding:
    problem_id: str
    scenario_id: str
    turn: str
    severity: str
    message: str
    group: str = ""


@dataclass
class ProblemAuditResult:
    problem_id: str
    report_dir: Path
    findings: list[Finding] = field(default_factory=list)

    def add(
        self,
        scenario_id: str,
        turn: str,
        severity: str,
        message: str,
        group: str = "",
    ) -> None:
        self.findings.append(Finding(self.problem_id, scenario_id, turn, severity, message, group))

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "fail")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warn")


def _skills(plan: list[PlanStep]) -> list[str]:
    return [s.skill for s in plan]


def _plan_step(raw: dict[str, Any]) -> PlanStep:
    return PlanStep(skill=str(raw["skill"]), args=dict(raw.get("args") or {}))


def _is_review_ask_user(plan: list[PlanStep]) -> bool:
    for step in plan:
        if step.skill != "ask_user":
            continue
        q = str((step.args or {}).get("question", ""))
        if "簡訊" in q or "訊息" in q:
            return True
    return False


def _mock_planner_factory(responses: list[PlannerOutput]):
    calls = {"i": 0}

    def _fn(**_kwargs: Any) -> PlannerOutput:
        i = calls["i"]
        calls["i"] = min(i + 1, len(responses) - 1)
        return responses[i]

    return _fn


def _mock_replan_factory(responses: list[ReplanOutput]):
    calls = {"i": 0}

    def _fn(**_kwargs: Any) -> ReplanOutput:
        i = calls["i"]
        calls["i"] = min(i + 1, len(responses) - 1)
        return responses[i]

    return _fn


def _planner_from_mock(mock: dict[str, Any]) -> PlannerOutput:
    todos = [_plan_step(t) for t in mock.get("todos") or []]
    return PlannerOutput(
        task_type=str(mock.get("task_type", "action")),
        task_state=str(mock.get("task_state", "running")),
        todos=todos,
        message=str(mock.get("message", "")),
    )


def _replan_from_mock(mock: dict[str, Any]) -> ReplanOutput:
    return ReplanOutput(
        complete=bool(mock.get("complete", True)),
        final_answer=str(mock.get("final_answer", "")),
        updated_todos=[_plan_step(t) for t in mock.get("updated_todos") or []],
        task_state=str(mock.get("task_state", "completed")),
        waiting_input=bool(mock.get("waiting_input", False)),
        user_prompt=str(mock.get("user_prompt", "")),
    )


def _planner_responses_from_mock(mock: dict[str, Any]) -> list[PlannerOutput]:
    raw = mock.get("planner_responses")
    if raw:
        return [_planner_from_mock(r) for r in raw]
    default = mock.get("planner_default") or {
        "todos": [{"skill": "weather", "args": {"location": "台中"}}],
    }
    return [_planner_from_mock(default)] * 20


def _replan_responses_from_mock(mock: dict[str, Any]) -> list[ReplanOutput]:
    raw = mock.get("replan_responses")
    if raw:
        return [_replan_from_mock(r) for r in raw]
    default = mock.get("replan_default") or {"complete": True, "final_answer": "好的。"}
    return [_replan_from_mock(default)] * 20


def _memory_parse_fn_from_rules(rules: list[dict[str, Any]]):
    def parse_fn(user_text: str, **_kwargs: Any) -> dict[str, Any] | None:
        for rule in rules:
            needle = str(rule.get("match_contains", ""))
            hay = user_text.lower() if rule.get("ignore_case") else user_text
            n = needle.lower() if rule.get("ignore_case") else needle
            if n in hay:
                return dict(rule["decision"])
        return None

    return parse_fn


def _execute_step_factory(preset: str):
    fn = _EXECUTE_MOCKS.get(preset)
    if fn is None:
        raise ValueError(f"未知 execute_step preset: {preset}")
    return fn


def _check_plan_execute_expect(
    result: ProblemAuditResult,
    *,
    sid: str,
    user_text: str,
    expect: dict[str, Any],
    group: str,
    severity: str,
    got_skills: list[str],
    pr: bool,
    plan: list[PlanStep] | None = None,
    out_task_type: str = "",
    answer: str = "",
) -> None:
    if "skills" in expect and got_skills != list(expect["skills"]):
        result.add(sid, user_text, severity, f"skills 應為 {expect['skills']}；實際 {got_skills}", group)
    if "pending_review" in expect and pr != bool(expect["pending_review"]):
        result.add(
            sid,
            user_text,
            severity,
            f"pending_review 應為 {expect['pending_review']}；實際 {pr}",
            group,
        )
    if expect.get("forbid_review_ask_user") and plan and _is_review_ask_user(plan):
        result.add(
            sid,
            user_text,
            severity,
            f"不應再出現審查 ask_user；plan={got_skills} pending_review={pr}",
            group,
        )
    if "task_type" in expect and out_task_type and out_task_type != str(expect["task_type"]):
        result.add(sid, user_text, severity, f"task_type 應為 {expect['task_type']}；實際 {out_task_type}", group)
    allowed_skills = list(expect.get("skills_one_of") or [])
    if allowed_skills and got_skills not in allowed_skills:
        result.add(sid, user_text, severity, f"skills 應為其中之一 {allowed_skills}；實際 {got_skills}", group)
    forbidden = list(expect.get("forbidden_skills") or [])
    for skill in forbidden:
        if skill in got_skills:
            result.add(sid, user_text, severity, f"不應出現 skill {skill}", group)
    for frag in list(expect.get("answer_contains") or []):
        if frag not in (answer or ""):
            result.add(sid, user_text, severity, f"回覆應含「{frag}」", group)


def _memory_patch(rules: list[dict[str, Any]]):
    parse_fn = _memory_parse_fn_from_rules(rules)

    def _try(user_text: str, **kwargs: Any):
        return try_handle_memory_turn(user_text, parse_fn=parse_fn, **kwargs)

    return patch("dual_agent.cai.plan_execute.try_handle_memory_turn", side_effect=_try)


def _expect_bool(actual: bool, expect: dict[str, Any], key: str, positive: bool = True) -> bool:
    if key not in expect:
        return True
    wanted = bool(expect[key])
    return actual == wanted if positive else actual != wanted


def _run_ingress_scenario(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    sid = str(scenario["id"])
    for turn in scenario.get("turns") or []:
        user_text = str(turn["user"])
        expect = dict(turn.get("expect") or {})
        group = str(turn.get("group") or "")
        severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
        ing = normalize_ingress(raw_input_text=user_text, input_origin=str(turn.get("input_origin") or "chat_box"))
        itt = str(ing.detected_task_type)
        rpc = bool((ing.metadata or {}).get("review_pending_candidate"))
        review_intent = looks_like_review_intent_without_artifact(user_text, ing.entities)

        if "requires_dai" in expect and bool(ing.requires_dai) != bool(expect["requires_dai"]):
            result.add(sid, user_text, severity, f"requires_dai 應為 {expect['requires_dai']}；實際 {ing.requires_dai}", group)
        if "review_pending_candidate" in expect and rpc != bool(expect["review_pending_candidate"]):
            result.add(sid, user_text, severity, f"review_pending_candidate 應為 {expect['review_pending_candidate']}；實際 {rpc}", group)
        if "detected_task_type" in expect and itt != str(expect["detected_task_type"]):
            result.add(sid, user_text, severity, f"detected_task_type 應為 {expect['detected_task_type']}；實際 {itt}", group)
        not_type = expect.get("detected_task_type_not")
        if not_type and itt == str(not_type):
            result.add(sid, user_text, severity, f"detected_task_type 不應為 {not_type}", group)
        if expect.get("review_intent_without_artifact") is False and review_intent:
            result.add(sid, user_text, severity, "不應判定為 review_intent_without_artifact", group)


def _run_validate_scenario(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    sid = str(scenario["id"])
    for turn in scenario.get("turns") or []:
        user_text = str(turn["user"])
        expect = dict(turn.get("expect") or {})
        group = str(turn.get("group") or "")
        severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
        input_plan = [_plan_step(t) for t in turn.get("planner_todos") or []]
        todos, tt, _, _ = validate_planner_output(
            user_text=user_text,
            task_type=str(turn.get("task_type", "action")),
            task_state=str(turn.get("task_state", "running")),
            todos=input_plan,
            message=str(turn.get("message", "")),
            pending_review=bool(turn.get("pending_review", False)),
        )
        got_skills = _skills(todos)
        if "task_type" in expect and tt != str(expect["task_type"]):
            result.add(sid, user_text, severity, f"task_type 應為 {expect['task_type']}；實際 {tt}", group)
        if "skills" in expect and got_skills != list(expect["skills"]):
            result.add(sid, user_text, severity, f"skills 應為 {expect['skills']}；實際 {got_skills}", group)
        forbidden = list(expect.get("forbidden_skills") or [])
        for skill in forbidden:
            if skill in got_skills:
                result.add(sid, user_text, severity, f"不應出現 skill {skill}", group)


def _run_semantic_router_scenario(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    sid = str(scenario["id"])
    for turn in scenario.get("turns") or []:
        user_text = str(turn["user"])
        expect = dict(turn.get("expect") or {})
        severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
        routed = route_user_text(user_text)
        if "confidence" in expect and routed.confidence != str(expect["confidence"]):
            result.add(sid, user_text, severity, f"confidence 應為 {expect['confidence']}；實際 {routed.confidence}")
        if "skills" in expect and _skills(routed.todos) != list(expect["skills"]):
            result.add(sid, user_text, severity, f"router skills 應為 {expect['skills']}；實際 {_skills(routed.todos)}")
        if "task_type" in expect and routed.task_type != str(expect["task_type"]):
            result.add(sid, user_text, severity, f"router task_type 應為 {expect['task_type']}；實際 {routed.task_type}")
        if turn.get("apply_over_planner"):
            wrong = [_plan_step(t) for t in turn["apply_over_planner"]]
            todos, _, _, applied = apply_semantic_router(
                user_text=user_text,
                todos=wrong,
                task_type="action",
                task_state="running",
                ingress_requires_dai=False,
                ingress_detected_task_type="action",
            )
            if expect.get("router_applied") and not applied:
                result.add(sid, user_text, severity, "apply_semantic_router 應覆寫 planner")
            if "skills" in expect and _skills(todos) != list(expect["skills"]):
                result.add(sid, user_text, severity, f"apply 後 skills 應為 {expect['skills']}；實際 {_skills(todos)}")


def _run_plan_execute_multiturn(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    sid = str(scenario["id"])
    mock = dict(scenario.get("mock") or {})
    planner_responses = _planner_responses_from_mock(mock)
    replan_responses = _replan_responses_from_mock(mock)
    replan_mock = _mock_replan_factory(replan_responses)
    planner_mock = _mock_planner_factory(planner_responses)
    ctx = SkillContext(user_input="")
    allow_memory = bool(scenario.get("allow_memory"))
    memory_rules = list(scenario.get("memory_parse_rules") or [])
    execute_preset = str(mock.get("execute_step") or "")
    memory_ctx = _memory_patch(memory_rules) if allow_memory and memory_rules else None
    executed_skills: list[str] = []

    def _execute_with_track(step: object, skill_ctx: SkillContext) -> SkillResult:
        executed_skills.append(str(getattr(step, "skill", "")))
        return _execute_step_factory(execute_preset)(step, skill_ctx)

    def _run_turns() -> None:
        for turn in scenario.get("turns") or []:
            user_text = str(turn["user"])
            expect = dict(turn.get("expect") or {})
            group = str(turn.get("group") or "")
            severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
            out = run_plan_and_execute(user_text=user_text, ctx=ctx)
            got_skills = _skills(out.plan)
            pr = bool(ctx.policy_state.get("pending_review"))
            if "executed_skills" in expect and executed_skills != list(expect["executed_skills"]):
                result.add(
                    sid,
                    user_text,
                    severity,
                    f"executed_skills 應為 {expect['executed_skills']}；實際 {executed_skills}",
                    group,
                )
            _check_plan_execute_expect(
                result,
                sid=sid,
                user_text=user_text,
                expect=expect,
                group=group,
                severity=severity,
                got_skills=got_skills,
                pr=pr,
                plan=out.plan,
                out_task_type=out.task_type,
                answer=out.answer or "",
            )

    planner_patch = patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=planner_mock)
    replan_patch = patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=replan_mock)
    memory_off_patch = (
        None if (allow_memory and memory_rules) else patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None)
    )
    execute_patch = (
        patch("dual_agent.cai.plan_execute.execute_step", side_effect=_execute_with_track) if execute_preset else None
    )

    with planner_patch, replan_patch:
        if memory_ctx:
            with memory_ctx:
                if execute_patch:
                    with execute_patch:
                        _run_turns()
                else:
                    _run_turns()
        elif memory_off_patch:
            with memory_off_patch:
                if execute_patch:
                    with execute_patch:
                        _run_turns()
                else:
                    _run_turns()
        elif execute_patch:
            with execute_patch:
                _run_turns()
        else:
            _run_turns()


def _run_memory_multiturn(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    sid = str(scenario["id"])
    rules = list(scenario.get("memory_parse_rules") or [])
    parse_fn = _memory_parse_fn_from_rules(rules)
    ctx = SkillContext(user_input="")
    ctx.policy_state["user_facts"] = normalize_user_facts(None)

    for turn in scenario.get("turns") or []:
        user_text = str(turn["user"])
        expect = dict(turn.get("expect") or {})
        group = str(turn.get("group") or "")
        severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
        out = try_handle_memory_turn(
            user_text,
            ctx=ctx,
            user_facts=normalize_user_facts(ctx.policy_state.get("user_facts")),
            model="mock",
            base_url="http://localhost",
            parse_fn=parse_fn,
        )
        answer = (out.answer if out else "") or ""
        if expect.get("memory_hit") is True and out is None:
            result.add(sid, user_text, severity, "記憶管線應命中但未回傳", group)
        if expect.get("memory_hit") is False and out is not None:
            result.add(sid, user_text, severity, "記憶管線不應命中", group)
        for frag in list(expect.get("answer_contains") or []):
            if frag not in answer:
                result.add(sid, user_text, severity, f"回覆應含「{frag}」；實際「{answer[:80]}」", group)
        rel_expect = dict(expect.get("relations") or {})
        if rel_expect:
            uf = normalize_user_facts(ctx.policy_state.get("user_facts"))
            relations = uf.get("relations") or {}
            for rel, names in rel_expect.items():
                got = relations.get(rel)
                if got != names:
                    result.add(sid, user_text, severity, f"relations[{rel}] 應為 {names}；實際 {got}", group)


def _run_risk_analysis_scenario(
    result: ProblemAuditResult,
    scenario: dict[str, Any],
    default_severity: str,
) -> None:
    """直接跑 DAI run_risk_analysis（可設 fusion_mode／雙路開關；關閉 semantic LLM）。"""
    import os

    from dual_agent.dai.risk_analysis.pipeline import run_risk_analysis
    from dual_agent.dai.schemas import DAIRequest

    sid = str(scenario["id"])
    fusion_mode = str(scenario.get("fusion_mode") or "legacy")
    prev_mode = os.environ.get("DAI_RISK_FUSION_MODE")
    prev_sem = os.environ.get("DAI_SEMANTIC_LLM")
    prev_pb = os.environ.get("DAI_DUAL_PATH_B")
    prev_nr = os.environ.get("DAI_DUAL_NARRATOR")
    os.environ["DAI_RISK_FUSION_MODE"] = fusion_mode
    os.environ["DAI_SEMANTIC_LLM"] = "0"
    if "dual_path_b" in scenario:
        os.environ["DAI_DUAL_PATH_B"] = "1" if scenario.get("dual_path_b") else "0"
    if "dual_narrator" in scenario:
        os.environ["DAI_DUAL_NARRATOR"] = "1" if scenario.get("dual_narrator") else "0"
    persona = scenario.get("persona") if isinstance(scenario.get("persona"), dict) else {}
    try:
        for turn in scenario.get("turns") or []:
            user_text = str(turn["user"])
            expect = dict(turn.get("expect") or {})
            group = str(turn.get("group") or "")
            severity = str(
                turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity
            )
            turn_persona = dict(persona)
            if isinstance(turn.get("persona"), dict):
                turn_persona.update(turn["persona"])
            report = run_risk_analysis(
                DAIRequest(
                    user_text=user_text,
                    artifact=user_text,
                    sms_review=True,
                    source="audit",
                    persona=turn_persona,
                ),
            )
            score = int(report.get("risk_score") or 0)
            verdict = str(report.get("verdict") or "")
            rf = report.get("risk_fusion") if isinstance(report.get("risk_fusion"), dict) else {}
            mode = str(rf.get("mode") or "")
            r_rules = int((report.get("component_scores") or {}).get("r_rules") or 0)
            path_a = report.get("path_a") if isinstance(report.get("path_a"), dict) else None
            engine = str(report.get("engine") or "")

            if "engine" in expect and engine != str(expect["engine"]):
                result.add(
                    sid,
                    user_text,
                    severity,
                    f"engine 應為 {expect['engine']}；實際 {engine}",
                    group,
                )
            if "verdict" in expect and verdict != str(expect["verdict"]):
                result.add(sid, user_text, severity, f"verdict 應為 {expect['verdict']}；實際 {verdict}", group)
            allowed = list(expect.get("verdict_one_of") or [])
            if allowed and verdict not in allowed:
                result.add(sid, user_text, severity, f"verdict 應為 {allowed} 之一；實際 {verdict}", group)
            if "min_risk_score" in expect and score < int(expect["min_risk_score"]):
                result.add(
                    sid,
                    user_text,
                    severity,
                    f"risk_score 應 ≥ {expect['min_risk_score']}；實際 {score}",
                    group,
                )
            if "max_risk_score" in expect and score > int(expect["max_risk_score"]):
                result.add(
                    sid,
                    user_text,
                    severity,
                    f"risk_score 應 ≤ {expect['max_risk_score']}；實際 {score}",
                    group,
                )
            frag = expect.get("risk_fusion_mode_contains")
            if frag and frag not in mode:
                result.add(
                    sid,
                    user_text,
                    severity,
                    f"risk_fusion.mode 應含「{frag}」；實際 {mode}",
                    group,
                )
            if expect.get("has_p_fraud") and rf.get("p_fraud") is None:
                result.add(sid, user_text, severity, "risk_fusion 應含 p_fraud", group)
            if "hard_guard_or_rules_ge" in expect:
                need = int(expect["hard_guard_or_rules_ge"])
                if r_rules < need and score < need:
                    result.add(
                        sid,
                        user_text,
                        severity,
                        f"硬擋／分數應 ≥ {need}（r_rules={r_rules}, score={score}）",
                        group,
                    )
            if expect.get("has_path_a") and not path_a:
                result.add(sid, user_text, severity, "report 應含 path_a", group)
            if expect.get("path_a_has_reasons") and path_a:
                reasons = path_a.get("reasons") or []
                if not reasons:
                    result.add(sid, user_text, severity, "path_a.reasons 不可為空", group)
    finally:
        if prev_mode is None:
            os.environ.pop("DAI_RISK_FUSION_MODE", None)
        else:
            os.environ["DAI_RISK_FUSION_MODE"] = prev_mode
        if prev_sem is None:
            os.environ.pop("DAI_SEMANTIC_LLM", None)
        else:
            os.environ["DAI_SEMANTIC_LLM"] = prev_sem
        if prev_pb is None:
            os.environ.pop("DAI_DUAL_PATH_B", None)
        else:
            os.environ["DAI_DUAL_PATH_B"] = prev_pb
        if prev_nr is None:
            os.environ.pop("DAI_DUAL_NARRATOR", None)
        else:
            os.environ["DAI_DUAL_NARRATOR"] = prev_nr


def run_problem_scenarios(problem_dir: Path, spec: dict[str, Any]) -> ProblemAuditResult:
    problem_id = str(spec.get("problem_id") or problem_dir.name)
    status = str(spec.get("status", "open"))
    result = ProblemAuditResult(problem_id=problem_id, report_dir=problem_dir)
    if status == "fixed":
        return result

    default_severity = str(spec.get("default_severity_on_fail", "fail"))
    runners = {
        "ingress": _run_ingress_scenario,
        "validate": _run_validate_scenario,
        "semantic_router": _run_semantic_router_scenario,
        "plan_execute_multiturn": _run_plan_execute_multiturn,
        "memory_multiturn": _run_memory_multiturn,
        "risk_analysis": _run_risk_analysis_scenario,
    }
    for scenario in spec.get("scenarios") or []:
        stype = str(scenario.get("type", ""))
        runner = runners.get(stype)
        if not runner:
            result.add(str(scenario.get("id", stype)), "", "warn", f"未知 scenario type: {stype}")
            continue
        runner(result, scenario, default_severity)
    return result


def discover_problem_dirs(test_reports_root: Path) -> list[Path]:
    if not test_reports_root.is_dir():
        return []
    dirs: list[Path] = []
    for child in sorted(test_reports_root.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "scenarios.json").is_file():
            dirs.append(child)
    return dirs


def load_problem_spec(problem_dir: Path) -> dict[str, Any]:
    path = problem_dir / "scenarios.json"
    return json.loads(path.read_text(encoding="utf-8"))


def write_audit_json(result: ProblemAuditResult) -> Path:
    payload = [
        {
            "problem_id": f.problem_id,
            "scenario_id": f.scenario_id,
            "group": f.group,
            "turn": f.turn,
            "severity": f.severity,
            "message": f.message,
        }
        for f in result.findings
    ]
    out_path = result.report_dir / "audit_latest.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def print_results(results: list[ProblemAuditResult]) -> int:
    total_fail = sum(r.fail_count for r in results)
    total_warn = sum(r.warn_count for r in results)
    total = sum(len(r.findings) for r in results)
    print(f"\n=== 問題導向審計：{total_fail} fail, {total_warn} warn, {total} total ===\n")
    for result in results:
        if not result.findings and load_problem_spec(result.report_dir).get("status") == "fixed":
            print(f"[SKIP] {result.problem_id}（status=fixed）\n")
            continue
        if not result.findings:
            print(f"[PASS] {result.problem_id}\n")
            continue
        print(f"--- {result.problem_id} ---")
        for f in result.findings:
            group_tag = f" [{f.group}]" if f.group else ""
            print(f"[{f.severity.upper()}] {f.scenario_id}{group_tag} | {f.turn}")
            print(f"       {f.message}\n")
    return 1 if total_fail else 0


def run_all(test_reports_root: Path | None = None) -> tuple[int, list[ProblemAuditResult]]:
    root = test_reports_root or (_ROOT / "test_reports")
    results: list[ProblemAuditResult] = []
    for problem_dir in discover_problem_dirs(root):
        spec = load_problem_spec(problem_dir)
        result = run_problem_scenarios(problem_dir, spec)
        write_audit_json(result)
        results.append(result)
    return print_results(results), results
