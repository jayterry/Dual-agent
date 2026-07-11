"""
Dual-agent 里程碑一：桌面 CAI（交流 + Plan & Execute）。

實作於本倉庫 `dual_agent` 套件內；**執行時不依賴**工作區內其他僅供人閱讀之參考資料夾。
執行前請安裝 `requirements.txt`，並確保 Ollama 可用。

  cd Dual-agent
  python desktop_cai_app.py
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext, ttk
from typing import Any

# 確保以「Dual-agent」目錄為根時可 import dual_agent
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _extract_latest_call_dai_payload(results: list[Any]) -> dict[str, Any] | None:
    for r in reversed(results):
        if getattr(r, "skill", "") != "call_dai":
            continue
        data = getattr(r, "data", {}) or {}
        dai = data.get("dai")
        if isinstance(dai, dict):
            return dai
    return None


def _build_dai_result_block(results: list[Any]) -> str:
    dai = _extract_latest_call_dai_payload(results)
    if not dai:
        return ""

    lines = ["【DAI 風險摘要】"]
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


def _clip_step_text(value: Any, *, max_chars: int = 80) -> str:
    s = " ".join(str(value or "").strip().split())
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _display_step_args(skill: str, args: dict[str, Any]) -> dict[str, Any]:
    if skill == "ask_user":
        return {"question": _clip_step_text(args.get("question"), max_chars=80)}
    if skill in ("open_url", "open_url_readonly"):
        return {"url": args.get("url")}
    if skill == "search_web":
        return {"query": _clip_step_text(args.get("query"), max_chars=80)}
    if skill == "weather":
        return {
            "location": _clip_step_text(args.get("location"), max_chars=60),
            "format": args.get("format"),
        }
    if skill == "instant_answer":
        return {"query": _clip_step_text(args.get("query"), max_chars=80)}
    if skill == "fetch_url":
        return {"url": _clip_step_text(args.get("url"), max_chars=100)}
    if skill == "open_app":
        return {"name": args.get("name"), "path": args.get("path")}
    if skill == "call_dai":
        shown: dict[str, Any] = {}
        artifact = _clip_step_text(args.get("artifact"), max_chars=120)
        user_text = _clip_step_text(args.get("user_text"), max_chars=80)
        if artifact:
            shown["artifact"] = artifact
        if user_text:
            shown["user_text"] = user_text
        if "sms_review" in args:
            shown["sms_review"] = bool(args.get("sms_review"))
        if args.get("context_pack"):
            shown["context_pack"] = "（已省略）"
        return shown
    return {k: _clip_step_text(args.get(k), max_chars=80) for k in list(args.keys())[:3]}


def _build_plan_block(plan: list[Any]) -> str:
    lines = [f"計畫步驟數：{len(plan)}"]
    for i, st in enumerate(plan, 1):
        args = getattr(st, "args", None) or {}
        shown = _display_step_args(getattr(st, "skill", ""), args)
        lines.append(f"  {i}. {st.skill} {shown}")
    return "\n".join(lines)


def _build_memory_assistant_text(answer: str, results: list[Any]) -> str:
    # 記憶只保留自然語言回答與 DAI 摘要，避免把 plan / context_pack 汙染回下一輪 prompt。
    base = (answer or "").strip()
    dai_block = _build_dai_result_block(results)
    if base and dai_block:
        return f"{base}\n\n{dai_block}"
    return base or dai_block


def _load_auto_jobs(problem_id: str) -> list[dict[str, Any]]:
    """從 test_reports 載入可在桌面 CAI 跑的真實 Ollama 對話輪次。"""
    import json

    path = _ROOT / "test_reports" / problem_id / "scenarios.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    jobs: list[dict[str, Any]] = []
    for scenario in spec.get("scenarios") or []:
        stype = str(scenario.get("type", ""))
        if stype not in ("plan_execute_multiturn", "memory_multiturn"):
            continue
        sid = str(scenario.get("id", ""))
        for i, turn in enumerate(scenario.get("turns") or []):
            jobs.append(
                {
                    "scenario_id": sid,
                    "group": str(turn.get("group") or ""),
                    "ref": str(turn.get("ref") or ""),
                    "user": str(turn["user"]),
                    "fresh_session": i == 0,
                }
            )
    return jobs


def _write_auto_dialogue(problem_id: str, rows: list[dict[str, Any]]) -> Path:
    from datetime import datetime, timedelta, timezone

    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    out_dir = _ROOT / "test_dialogue" / problem_id
    out_dir.mkdir(parents=True, exist_ok=True)
    base = now.strftime("%Y-%m-%d_桌面CAI對話")
    out_path = out_dir / f"{base}.md"
    n = 2
    while out_path.exists():
        out_path = out_dir / f"{base}_{n}.md"
        n += 1

    lines = [
        f"# 測試對話：{problem_id}（桌面 CAI）",
        "",
        "| 項目 | 內容 |",
        "|------|------|",
        f"| 日期 | {now.strftime('%Y-%m-%d %H:%M')} (UTC+8) |",
        "| 測試者 | **Cursor**（`desktop_cai_app.py --auto-problem`） |",
        "| 環境 | 桌面 CAI + 真實 Ollama Planner/Replan + SessionMemory |",
        f"| 對應回報 | [`test_reports/{problem_id}/`](../../test_reports/{problem_id}/) |",
        f"| 本輪判定 | {len(rows)} 輪已執行 |",
        "",
        "## 對話（視窗內即時展示）",
        "",
        "| # | 情境 | 測試者輸入 | task_type | 計畫步驟 | pending_review | 回覆摘要 |",
        "|---|------|-----------|-----------|----------|----------------|----------|",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | `{row['scenario_id']}` / {row['ref']} | {row['user']} | {row['task_type']} | "
            f"{row['plan']} | {row['pending_review']} | {row['answer']} |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    import argparse

    from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
    from dual_agent.logutil import get_logger, setup_logging
    from dual_agent.cai.plan_execute import run_plan_and_execute
    from dual_agent.skill_types import SkillContext

    parser = argparse.ArgumentParser(description="Dual-agent 桌面 CAI")
    parser.add_argument(
        "--auto-problem",
        default=None,
        help="自動在視窗內跑 test_reports 劇本（plan_execute + memory multiturn）",
    )
    args = parser.parse_args()
    auto_jobs = _load_auto_jobs(args.auto_problem) if args.auto_problem else []

    setup_logging(level="INFO", log_file=None)
    log = get_logger("desktop_cai")

    root = tk.Tk()
    root.title("Dual-agent · CAI（里程碑一 · 內建 Plan & Execute）")
    root.geometry("820x560")

    frm = ttk.Frame(root, padding=8)
    frm.pack(fill=tk.BOTH, expand=True)

    ttk.Label(
        frm,
        text="模型 / Ollama（OLLAMA_MODEL、OLLAMA_BASE_URL）",
    ).pack(anchor=tk.W)
    status_var = tk.StringVar(value=f"Ollama: {OLLAMA_BASE_URL}　模型: {OLLAMA_MODEL}")
    busy_var = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status_var, foreground="#333").pack(anchor=tk.W)
    ttk.Label(frm, textvariable=busy_var, foreground="#a50").pack(anchor=tk.W)

    chat = scrolledtext.ScrolledText(frm, height=22, wrap=tk.WORD, state=tk.DISABLED)
    chat.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

    input_frm = ttk.Frame(frm)
    input_frm.pack(fill=tk.X)
    entry = tk.Text(input_frm, height=3, wrap=tk.WORD)
    entry.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

    btn_frm = ttk.Frame(input_frm)
    btn_frm.pack(side=tk.RIGHT, fill=tk.Y)
    send_btn = ttk.Button(btn_frm, text="送出")
    send_btn.pack(fill=tk.X)
    clear_btn = ttk.Button(btn_frm, text="清空輸入")
    clear_btn.pack(fill=tk.X, pady=(6, 0))
    new_chat_btn = ttk.Button(btn_frm, text="新對話")
    new_chat_btn.pack(fill=tk.X, pady=(6, 0))

    from dual_agent.cai.context_layer import SessionMemory, build_plan_summary, build_context_pack_for_turn, record_turn
    from dual_agent.cai.executor import format_results_for_display

    q: queue.Queue[tuple[str, str | None, dict[str, Any] | None]] = queue.Queue()
    ctx = SkillContext(user_input="")
    session = SessionMemory()
    auto_index = 0
    auto_rows: list[dict[str, Any]] = []
    auto_running = bool(auto_jobs)

    def append_chat(who: str, text: str) -> None:
        chat.configure(state=tk.NORMAL)
        chat.insert(tk.END, f"{who}\n{text}\n\n")
        chat.see(tk.END)
        chat.configure(state=tk.DISABLED)

    def reset_session() -> None:
        nonlocal ctx, session
        ctx = SkillContext(user_input="")
        session = SessionMemory()

    def worker(user_message: str, job: dict[str, Any] | None = None) -> None:
        meta: dict[str, Any] | None = None
        try:
            cp = build_context_pack_for_turn(
                session,
                user_message,
                user_facts=ctx.policy_state.get("user_facts"),
                pending_memory_confirm=ctx.policy_state.get("pending_memory_confirm"),
            )
            out = run_plan_and_execute(user_text=user_message, ctx=ctx, context_pack=cp)
            plan_block = _build_plan_block(out.plan)
            result_summary = (
                format_results_for_display(out.results) if out.results else "（本輪無 Executor 結果）"
            )
            memory_answer = _build_memory_assistant_text(out.answer, out.results)
            answer_text = f"{plan_block}\n\n{memory_answer}" if memory_answer else plan_block
            plan_detail = " → ".join(
                f"{s.skill} {dict(s.args or {})}" for s in out.plan
            ) or "（空）"
            meta = {
                "scenario_id": (job or {}).get("scenario_id", "manual"),
                "ref": (job or {}).get("ref", "手動"),
                "user": user_message,
                "task_type": out.task_type,
                "plan": plan_detail,
                "pending_review": bool(ctx.policy_state.get("pending_review")),
                "answer": (memory_answer or answer_text)[:200],
            }
            q.put(("assistant", answer_text, meta))
            record_turn(
                session,
                user=user_message,
                assistant=memory_answer,
                task_type=out.task_type,
                task_state=out.task_state,
                model=OLLAMA_MODEL,
                base_url=OLLAMA_BASE_URL,
                plan_summary=build_plan_summary(out.plan),
                result_summary=result_summary,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("run_plan_and_execute 失敗")
            q.put(("assistant", f"（錯誤）{e}", meta))

    def start_auto_turn() -> None:
        nonlocal auto_index, auto_running
        if auto_index >= len(auto_jobs):
            auto_running = False
            reset_session()
            out_path = _write_auto_dialogue(args.auto_problem or "", auto_rows)
            busy_var.set("")
            send_btn.configure(state=tk.NORMAL)
            append_chat(
                "系統",
                f"劇本執行完畢（共 {len(auto_rows)} 輪）。測試脈絡已清空，可開始手動對話。\n紀錄已寫入：\n{out_path}",
            )
            return
        job = auto_jobs[auto_index]
        if job.get("fresh_session"):
            reset_session()
        user_text = str(job["user"])
        append_chat("你", user_text)
        busy_var.set(f"自動劇本 {auto_index + 1}/{len(auto_jobs)}：思考與執行中…")
        send_btn.configure(state=tk.DISABLED)
        threading.Thread(target=worker, args=(user_text, job), daemon=True).start()

    def on_send() -> None:
        if auto_running:
            return
        raw = entry.get("1.0", tk.END).strip()
        if not raw:
            return
        append_chat("你", raw)
        entry.delete("1.0", tk.END)
        send_btn.configure(state=tk.DISABLED)
        busy_var.set("思考與執行中…")
        threading.Thread(target=worker, args=(raw, None), daemon=True).start()

    def poll_queue() -> None:
        nonlocal auto_index, auto_running
        try:
            while True:
                role, text, meta = q.get_nowait()
                if role == "assistant":
                    busy_var.set("")
                    append_chat("助理", text or "")
                    if meta:
                        auto_rows.append(meta)
                    if auto_running:
                        auto_index += 1
                        root.after(600, start_auto_turn)
                    else:
                        send_btn.configure(state=tk.NORMAL)
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    def on_clear() -> None:
        entry.delete("1.0", tk.END)

    def on_new_chat() -> None:
        if auto_running:
            return
        reset_session()
        append_chat("系統", "已開始新對話（記憶與待審狀態已清空）。")

    send_btn.configure(command=on_send)
    clear_btn.configure(command=on_clear)
    new_chat_btn.configure(command=on_new_chat)
    entry.bind("<Control-Return>", lambda _e: on_send())

    intro = (
        "【CAI】Planner →（Todo 非空則）Executor 執行第一項 → Replan 迴圈。\n"
        "【Memory】已啟用 Context Pack：長期摘要 + 最近 10 輪緩衝 + 任務狀態（緩衝溢出會壓縮進摘要，需 Ollama）。\n\n"
    )
    if auto_jobs:
        intro += (
            f"【自動劇本】`{args.auto_problem}`：共 {len(auto_jobs)} 輪（CAI multiturn + Memory）。\n"
            "Ingress / Router / Validate 單元段請見 mock 審計紀錄。\n"
            "即將自動開始…\n"
        )
        send_btn.configure(state=tk.DISABLED)
    else:
        intro += "輸入問題或 (skill:…) 指令。\n（Ctrl+Enter 送出）"
    append_chat("系統", intro)
    poll_queue()
    if auto_jobs:
        root.after(1200, start_auto_turn)
    root.mainloop()


if __name__ == "__main__":
    main()
