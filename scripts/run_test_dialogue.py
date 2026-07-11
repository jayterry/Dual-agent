#!/usr/bin/env python3
"""執行 test_reports 內 scenarios，並將與 Dual-agent 的測試對話寫入 test_dialogue。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.cai.planner_validate import validate_planner_output
from dual_agent.cai.schemas import PlanStep, PlannerOutput, ReplanOutput
from dual_agent.skill_types import SkillContext
from scripts.problem_report_runner import load_problem_spec, run_all

TZ8 = timezone(timedelta(hours=8))
GROUP_LABELS = {
    "baseline": "歷史重現",
    "control": "對照組",
    "experimental": "實驗組",
}


def _skills(plan: list[PlanStep]) -> list[str]:
    return [s.skill for s in plan]


def _plan_step(raw: dict[str, Any]) -> PlanStep:
    return PlanStep(skill=str(raw["skill"]), args=dict(raw.get("args") or {}))


def _planner_from_mock(mock: dict[str, Any]) -> PlannerOutput:
    return PlannerOutput(
        task_type=str(mock.get("task_type", "action")),
        task_state=str(mock.get("task_state", "running")),
        todos=[_plan_step(t) for t in mock.get("todos") or []],
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


def _is_review_ask_user(plan: list[PlanStep]) -> bool:
    for step in plan:
        if step.skill != "ask_user":
            continue
        q = str((step.args or {}).get("question", ""))
        if "簡訊" in q or "訊息" in q:
            return True
    return False


def _check_turn(expect: dict[str, Any], out, ctx: SkillContext) -> str:
    got_skills = _skills(out.plan)
    pr = bool(ctx.policy_state.get("pending_review"))
    issues: list[str] = []
    if "skills" in expect and got_skills != list(expect["skills"]):
        issues.append(f"skills 預期 {expect['skills']} 實際 {got_skills}")
    if "pending_review" in expect and pr != bool(expect["pending_review"]):
        issues.append(f"pending_review 預期 {expect['pending_review']} 實際 {pr}")
    if expect.get("forbid_review_ask_user") and _is_review_ask_user(out.plan):
        issues.append("仍為審查 ask_user")
    allowed = list(expect.get("skills_one_of") or [])
    if allowed and got_skills not in allowed:
        issues.append(f"skills 應為其中之一 {allowed}")
    return "✓" if not issues else "✗ " + "；".join(issues)


def _turn_row(
    *,
    scenario_id: str,
    group: str,
    ref: str,
    user: str,
    task_type: str,
    task_state: str,
    plan: str,
    answer: str,
    pending_review: Any,
    ok: str,
) -> dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "group": group,
        "group_label": GROUP_LABELS.get(group, group or "—"),
        "ref": ref,
        "user": user,
        "task_type": task_type,
        "task_state": task_state,
        "plan": plan,
        "answer": answer,
        "pending_review": pending_review,
        "ok": ok,
    }


def run_multiturn_dialogue(scenario: dict[str, Any], *, live: bool = False) -> list[dict[str, Any]]:
    sid = str(scenario.get("id", ""))
    mock = dict(scenario.get("mock") or {})
    planner_default = _planner_from_mock(
        mock.get("planner_default") or {"todos": [{"skill": "weather", "args": {"location": "台中"}}]}
    )
    replan_default = _replan_from_mock(mock.get("replan_default") or {"complete": True, "final_answer": "好的。"})
    rows: list[dict[str, Any]] = []
    ctx = SkillContext(user_input="")

    def planner_fn(**_kwargs: Any) -> PlannerOutput:
        return planner_default

    def replan_fn(**_kwargs: Any) -> ReplanOutput:
        return replan_default

    def _run_turn(turn: dict[str, Any]) -> None:
        user_text = str(turn["user"])
        expect = dict(turn.get("expect") or {})
        group = str(turn.get("group") or "")
        ref = str(turn.get("ref") or "")
        out = run_plan_and_execute(user_text=user_text, ctx=ctx)
        plan_detail = [f"{s.skill} {dict(s.args or {})}" for s in out.plan]
        rows.append(
            _turn_row(
                scenario_id=sid,
                group=group,
                ref=ref,
                user=user_text,
                task_type=out.task_type,
                task_state=out.task_state,
                plan=" → ".join(plan_detail) if plan_detail else "（空）",
                answer=(out.answer or "")[:200],
                pending_review=bool(ctx.policy_state.get("pending_review")),
                ok=_check_turn(expect, out, ctx),
            )
        )

    if live:
        with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
            for turn in scenario.get("turns") or []:
                _run_turn(turn)
        return rows

    with patch("dual_agent.cai.plan_execute.try_handle_memory_turn", return_value=None):
        with patch("dual_agent.cai.plan_execute.invoke_planner", side_effect=planner_fn):
            with patch("dual_agent.cai.plan_execute.invoke_replan", side_effect=replan_fn):
                for turn in scenario.get("turns") or []:
                    _run_turn(turn)
    return rows


def run_validate_dialogue(scenario: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    sid = str(scenario.get("id", ""))
    user_text = str(turn["user"])
    input_plan = [_plan_step(t) for t in turn.get("planner_todos") or []]
    todos, tt, ts, _ = validate_planner_output(
        user_text=user_text,
        task_type=str(turn.get("task_type", "action")),
        task_state=str(turn.get("task_state", "running")),
        todos=input_plan,
        message=str(turn.get("message", "")),
        pending_review=bool(turn.get("pending_review", False)),
    )
    expect = dict(turn.get("expect") or {})
    got = _skills(todos)
    issues: list[str] = []
    if "task_type" in expect and tt != str(expect["task_type"]):
        issues.append(f"task_type 預期 {expect['task_type']} 實際 {tt}")
    for skill in list(expect.get("forbidden_skills") or []):
        if skill in got:
            issues.append(f"不應有 {skill}")
    return _turn_row(
        scenario_id=sid,
        group=str(turn.get("group") or ""),
        ref=str(turn.get("ref") or "validate"),
        user=user_text,
        task_type=tt,
        task_state=ts,
        plan=" → ".join(f"{s.skill}" for s in todos) if todos else "（空）",
        answer="—",
        pending_review="—",
        ok="✓" if not issues else "✗ " + "；".join(issues),
    )


def _next_output_path(problem_id: str, now: datetime, *, live: bool = False) -> Path:
    out_dir = _ROOT / "test_dialogue" / problem_id
    out_dir.mkdir(parents=True, exist_ok=True)
    base = now.strftime("%Y-%m-%d_Ollama對話" if live else "%Y-%m-%d_Cursor測試")
    candidate = out_dir / f"{base}.md"
    if not candidate.exists():
        return candidate
    n = 2
    while (out_dir / f"{base}_{n}.md").exists():
        n += 1
    return out_dir / f"{base}_{n}.md"


def write_dialogue_session(
    problem_id: str,
    spec: dict[str, Any],
    rows: list[dict[str, Any]],
    audit_code: int,
    pytest_summary: str,
    env_note: str,
    *,
    live: bool = False,
) -> Path:
    now = datetime.now(TZ8)
    out_path = _next_output_path(problem_id, now, live=live)
    design = dict(spec.get("test_design") or {})
    baseline_n = sum(1 for r in rows if r.get("group") == "baseline")
    control_n = sum(1 for r in rows if r.get("group") == "control")
    exp_n = sum(1 for r in rows if r.get("group") == "experimental")
    fail_n = sum(1 for r in rows if str(r.get("ok", "")).startswith("✗"))

    lines = [
        f"# 測試對話：{problem_id}",
        "",
        "| 項目 | 內容 |",
        "|------|------|",
        f"| 日期 | {now.strftime('%Y-%m-%d %H:%M')} (UTC+8) |",
        "| 測試者 | **Cursor** |",
        f"| 環境 | {env_note} |",
        f"| 對應回報 | [`test_reports/{problem_id}/`](../../test_reports/{problem_id}/) |",
        f"| 劇本設計 | 先 baseline（{baseline_n} 輪）→ experimental（{exp_n} 輪）＋ control（{control_n} 輪，獨立 session） |",
        f"| 審計 | {'通過' if audit_code == 0 else '有失敗'} |",
        f"| pytest | {pytest_summary} |",
        f"| 本輪判定 | {len(rows) - fail_n}/{len(rows)} 通過 |",
        "",
    ]
    if design.get("rule"):
        lines.extend(
            [
                "## 劇本原則",
                "",
                f"- {design['rule']}",
                f"- baseline 來源：{design.get('baseline_source', '—')}",
                "",
            ]
        )

    lines.extend(
        [
            "## 對話（測試者 → Dual-agent 管線）",
            "",
            "| # | 組別 | 情境 | 測試者輸入 | task_type | task_state | 計畫步驟 | pending_review | 回覆摘要 | 判定 |",
            "|---|------|------|-----------|-----------|------------|----------|----------------|----------|------|",
        ]
    )
    for i, r in enumerate(rows, 1):
        ans = (r.get("answer") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {i} | {r.get('group_label','')} | `{r.get('scenario_id','')}` "
            f"| `{r['user']}` | {r.get('task_type','')} | {r.get('task_state','')} "
            f"| {r.get('plan','')} | {r.get('pending_review','')} | {ans[:60]} | {r.get('ok','')} |"
        )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def collect_dialogue_rows(spec: dict[str, Any], *, live: bool = False) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in spec.get("scenarios") or []:
        stype = str(scenario.get("type", ""))
        if stype == "plan_execute_multiturn":
            rows.extend(run_multiturn_dialogue(scenario, live=live))
        elif stype == "validate" and not live:
            for turn in scenario.get("turns") or []:
                rows.append(run_validate_dialogue(scenario, turn))
    return rows


def main() -> int:
    import subprocess

    parser = argparse.ArgumentParser(description="執行問題導向測試並寫入 test_dialogue")
    parser.add_argument("--problem", default="pending_review_無法取消", help="test_reports 子資料夾名稱")
    parser.add_argument("--skip-pytest", action="store_true", help="略過 pytest 回歸")
    parser.add_argument("--live", action="store_true", help="真實 Ollama Planner/Replan（不 mock）")
    parser.add_argument("--skip-audit", action="store_true", help="略過 problem_reports 審計")
    args = parser.parse_args()

    problem_id = args.problem
    problem_dir = _ROOT / "test_reports" / problem_id
    spec = load_problem_spec(problem_dir)

    ollama_ok = False
    server_ok = False
    try:
        import urllib.request

        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        ollama_ok = True
    except Exception:
        pass
    try:
        import urllib.request

        urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=2)
        server_ok = True
    except Exception:
        pass
    if args.live:
        if not ollama_ok:
            print("錯誤：--live 需要 Ollama（localhost:11434）")
            return 1
        env_parts = ["真實 Ollama Planner/Replan（`run_plan_and_execute`）"]
        env_parts.append("Ollama 已啟動")
        env_parts.append("mobile_server 已啟動" if server_ok else "mobile_server **未啟動**（直連管線）")
    else:
        env_parts = ["mock Planner/Replan（`run_plan_and_execute`）"]
        env_parts.append("Ollama 已啟動" if ollama_ok else "Ollama **未啟動**")
        env_parts.append("mobile_server 已啟動" if server_ok else "mobile_server **未啟動**")
    env_note = "；".join(env_parts)

    rows = collect_dialogue_rows(spec, live=args.live)
    audit_code = 0
    if not args.skip_audit and not args.live:
        audit_code, _ = run_all()
    elif not args.skip_audit:
        audit_code, _ = run_all()

    pytest_line = "（略過）"
    pytest_rc = 0
    if not args.skip_pytest and not args.live:
        pytest_proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_plan_execute_ingress.py",
                "tests/test_planner_validate.py",
                "tests/test_planner_context.py",
                "-q",
                "--tb=no",
            ],
            cwd=str(_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        pytest_line = (pytest_proc.stdout or "").strip().split("\n")[-1] or "（無輸出）"
        pytest_rc = pytest_proc.returncode

    out_path = write_dialogue_session(
        problem_id, spec, rows, audit_code, pytest_line, env_note, live=args.live
    )
    print(f"測試對話已寫入 {out_path}")
    fail_n = sum(1 for r in rows if str(r.get("ok", "")).startswith("✗"))
    if fail_n:
        return 1
    return audit_code if pytest_rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
