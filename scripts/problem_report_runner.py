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
from dual_agent.ingress import normalize_ingress
from dual_agent.skill_types import SkillContext


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
        ing = normalize_ingress(raw_input_text=user_text, input_origin="chat_box")
        itt = str(ing.detected_task_type)
        rpc = bool((ing.metadata or {}).get("review_pending_candidate"))
        review_intent = looks_like_review_intent_without_artifact(user_text, ing.entities)

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
    planner_default = _planner_from_mock(mock.get("planner_default") or {"todos": [{"skill": "weather", "args": {"location": "台中"}}]})
    replan_default = _replan_from_mock(mock.get("replan_default") or {"complete": True, "final_answer": "好的。"})
    planner_mock = _mock_planner_factory([planner_default] * 20)
    replan_mock = _mock_replan_factory([replan_default] * 20)
    ctx = SkillContext(user_input="")

    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=planner_mock):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=replan_mock):
                for turn in scenario.get("turns") or []:
                    user_text = str(turn["user"])
                    expect = dict(turn.get("expect") or {})
                    group = str(turn.get("group") or "")
                    severity = str(turn.get("severity_on_fail") or scenario.get("severity_on_fail") or default_severity)
                    out = run_plan_and_execute(user_text=user_text, ctx=ctx)
                    got_skills = _skills(out.plan)
                    pr = bool(ctx.policy_state.get("pending_review"))

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
                    if expect.get("forbid_review_ask_user") and _is_review_ask_user(out.plan):
                        result.add(
                            sid,
                            user_text,
                            severity,
                            f"不應再出現審查 ask_user；plan={got_skills} pending_review={pr}",
                            group,
                        )
                    allowed_skills = list(expect.get("skills_one_of") or [])
                    if allowed_skills and got_skills not in allowed_skills:
                        result.add(sid, user_text, severity, f"skills 應為其中之一 {allowed_skills}；實際 {got_skills}", group)


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
