"""
ScamSentinel 桌面介面（Tkinter 備援）。

正式桌面殼請優先用 PySide6：
  python desktop_cai_qt.py

主畫面只顯示對話；建圖在設定；不露出計畫／技能／Ollama 內部細節。

  cd Dual-agent
  python desktop_cai_app.py
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_UI = {
    "bg": "#F5F6F8",
    "surface": "#FFFFFF",
    "border": "#CBD5E1",
    "text": "#111827",
    "muted": "#6B7280",
    "accent": "#0F766E",
    "accent_hover": "#0D9488",
    "user_bg": "#DDF3EF",
    "input_bg": "#FFFFFF",
    "busy": "#B45309",
    "placeholder": "#9CA3AF",
}

_PLACEHOLDER = "輸入訊息或貼上簡訊…（Ctrl+Enter 送出）"


def _extract_latest_call_dai_payload(results: list[Any]) -> dict[str, Any] | None:
    for r in reversed(results):
        if getattr(r, "skill", "") != "call_dai":
            continue
        data = getattr(r, "data", {}) or {}
        dai = data.get("dai")
        if isinstance(dai, dict):
            return dai
    return None


def _user_facing_dai_block(results: list[Any]) -> str:
    """使用者可見的風險摘要（無內部欄位名堆砌）。"""
    dai = _extract_latest_call_dai_payload(results)
    if not dai:
        return ""

    lines: list[str] = []
    path_a = dai.get("path_a") if isinstance(dai.get("path_a"), dict) else None
    path_b = dai.get("path_b") if isinstance(dai.get("path_b"), dict) else None

    score = dai.get("risk_score")
    verdict = str(dai.get("verdict") or "").strip()
    if isinstance(score, (int, float)) or verdict:
        head = "風險評估"
        if isinstance(score, (int, float)):
            head += f"：{int(score)}/100"
        if verdict:
            head += f"（{verdict}）"
        lines.append(head)

    if path_a:
        lines.append("")
        lines.append("路徑 A（機器分析）")
        lines.append(
            f"威脅 {path_a.get('threat_score_100', '—')}/100　"
            f"情境 {path_a.get('context_score_100', '—')}/100"
        )
        if path_a.get("scam_type"):
            lines.append(f"類型：{path_a.get('scam_type')}")
        for r in (path_a.get("reasons") or [])[:4]:
            lines.append(f"· {r}")
        for w in (path_a.get("warnings") or [])[:2]:
            lines.append(f"⚠ {w}")

    if path_b and not path_b.get("skipped"):
        lines.append("")
        lines.append("路徑 B（語意對照）")
        lines.append(
            f"威脅 {path_b.get('threat_score_100', '—')}/100　"
            f"情境 {path_b.get('context_score_100', '—')}/100"
        )
        for r in (path_b.get("reasons") or [])[:3]:
            lines.append(f"· {r}")
    elif path_b and path_b.get("skipped"):
        # 正式介面：略過細節，不噴 stack／host
        pass

    narrator = str(dai.get("narrator_text") or "").strip()
    if narrator:
        lines.append("")
        lines.append(narrator[:400])
    else:
        summary = str(dai.get("safety_summary") or "").strip()
        if summary and not path_a:
            lines.append(summary[:300])

    if not lines:
        display = str(dai.get("display_text") or "").strip()
        return display[:800] if display else ""
    return "\n".join(lines).strip()


def _build_user_facing_reply(answer: str, results: list[Any]) -> str:
    base = (answer or "").strip()
    dai = _user_facing_dai_block(results)
    if base and dai:
        return f"{base}\n\n{dai}"
    return base or dai or "已完成。"


def _load_auto_jobs(problem_id: str) -> list[dict[str, Any]]:
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
        f"| 日期 | {now.strftime('%Y-%m-%d %H:%M')} |",
        f"| 輪次 | {len(rows)} |",
        "",
        "| # | 情境 | 輸入 | 回覆摘要 |",
        "|---|------|------|----------|",
    ]
    for i, row in enumerate(rows, 1):
        lines.append(
            f"| {i} | `{row['scenario_id']}` / {row['ref']} | {row['user']} | {row['answer']} |"
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _default_persona() -> dict[str, str]:
    # relation_type／channel 由前置推斷；設定只留使用者側欄位
    return {
        "age_band": "25-39",
        "occupation": "other",
        "primary_apps": "SMS",
        "invest_exp": "",
    }


def _persona_dict_from_state(state: dict[str, str]) -> dict[str, Any]:
    apps = [a.strip() for a in str(state.get("primary_apps") or "").split(",") if a.strip()]
    if not apps:
        apps = ["SMS"]
    out: dict[str, Any] = {
        "age_band": state.get("age_band") or "25-39",
        "occupation": state.get("occupation") or "other",
        "primary_apps": apps,
    }
    inv = str(state.get("invest_exp") or "").strip()
    if inv:
        out["invest_exp"] = inv
    return out


def _open_settings_dialog(parent: tk.Misc, persona_state: dict[str, str]) -> None:
    win = tk.Toplevel(parent)
    win.title("個人設定")
    win.configure(bg=_UI["bg"])
    win.transient(parent)
    win.grab_set()
    win.geometry("440x360")
    win.resizable(False, False)

    pad = tk.Frame(win, bg=_UI["bg"], padx=20, pady=16)
    pad.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        pad,
        text="個人設定",
        bg=_UI["bg"],
        fg=_UI["text"],
        font=("Segoe UI Semibold", 14),
    ).pack(anchor=tk.W)
    tk.Label(
        pad,
        text="常用 App 代表你平常使用的管道。這則訊息從哪裡來、來訊者關係由系統自動判斷。",
        bg=_UI["bg"],
        fg=_UI["muted"],
        font=("Segoe UI", 9),
        wraplength=390,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(4, 14))

    form = tk.Frame(pad, bg=_UI["surface"], highlightbackground=_UI["border"], highlightthickness=1)
    form.pack(fill=tk.BOTH, expand=True)
    form_inner = tk.Frame(form, bg=_UI["surface"], padx=14, pady=12)
    form_inner.pack(fill=tk.BOTH, expand=True)

    age_var = tk.StringVar(value=persona_state.get("age_band", "25-39"))
    occ_var = tk.StringVar(value=persona_state.get("occupation", "other"))
    apps_var = tk.StringVar(value=persona_state.get("primary_apps", "SMS"))
    invest_var = tk.StringVar(value=persona_state.get("invest_exp", ""))

    def field(row: int, label: str, widget: tk.Widget) -> None:
        tk.Label(form_inner, text=label, bg=_UI["surface"], fg=_UI["text"], width=10, anchor=tk.W).grid(
            row=row, column=0, sticky=tk.W, pady=5
        )
        widget.grid(row=row, column=1, sticky=tk.EW, pady=5)
        form_inner.columnconfigure(1, weight=1)

    field(
        0,
        "年齡",
        ttk.Combobox(form_inner, textvariable=age_var, values=["<25", "25-39", "40-59", "60+"], state="readonly"),
    )
    field(
        1,
        "職業",
        ttk.Combobox(
            form_inner,
            textvariable=occ_var,
            values=["student", "office", "freelance", "retired", "other"],
            state="readonly",
        ),
    )
    field(2, "常用 App", ttk.Entry(form_inner, textvariable=apps_var))
    field(3, "投資經驗", ttk.Entry(form_inner, textvariable=invest_var))

    def save() -> None:
        persona_state["age_band"] = age_var.get()
        persona_state["occupation"] = occ_var.get()
        persona_state["primary_apps"] = apps_var.get()
        persona_state["invest_exp"] = invest_var.get()
        persona_state.pop("relation_type", None)
        persona_state.pop("channel", None)
        try:
            from dual_agent.cai.profile_store import upsert_fields

            upsert_fields(
                {
                    "age_band": persona_state["age_band"],
                    "occupation": persona_state["occupation"],
                    "primary_apps": persona_state["primary_apps"],
                    "invest_exp": persona_state["invest_exp"],
                }
            )
        except Exception:  # noqa: BLE001
            pass
        win.destroy()

    bar = tk.Frame(pad, bg=_UI["bg"])
    bar.pack(fill=tk.X, pady=(14, 0))
    tk.Button(bar, text="取消", command=win.destroy, padx=12, pady=4).pack(side=tk.RIGHT)
    tk.Button(
        bar,
        text="儲存",
        command=save,
        bg=_UI["accent"],
        fg="#FFFFFF",
        activebackground=_UI["accent_hover"],
        activeforeground="#FFFFFF",
        relief=tk.FLAT,
        padx=16,
        pady=4,
    ).pack(side=tk.RIGHT, padx=(0, 8))


def main() -> None:
    import argparse

    from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
    from dual_agent.logutil import get_logger, setup_logging
    from dual_agent.cai.plan_execute import run_plan_and_execute
    from dual_agent.cai.context_layer import (
        SessionMemory,
        build_plan_summary,
        build_context_pack_for_turn,
        record_turn,
    )
    from dual_agent.cai.executor import format_results_for_display
    from dual_agent.skill_types import SkillContext

    parser = argparse.ArgumentParser(description="ScamSentinel 桌面")
    parser.add_argument("--auto-problem", default=None)
    args = parser.parse_args()
    auto_jobs = _load_auto_jobs(args.auto_problem) if args.auto_problem else []

    setup_logging(level="INFO", log_file=None)
    log = get_logger("desktop_cai")

    root = tk.Tk()
    root.title("ScamSentinel")
    root.geometry("820x700")
    root.minsize(640, 560)
    root.configure(bg=_UI["bg"])

    # grid：聊天可伸縮，輸入列固定底部（避免對話框被擠掉）
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    shell = tk.Frame(root, bg=_UI["bg"])
    shell.grid(row=0, column=0, sticky="nsew", padx=16, pady=12)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)  # chat
    # row 0 = top, row 1 = chat, row 2 = status, row 3 = composer

    ui_font = tkfont.Font(family="Segoe UI", size=11)
    title_font = tkfont.Font(family="Segoe UI Semibold", size=13)
    small_font = tkfont.Font(family="Segoe UI", size=9)

    # —— 頂列 ——
    top = tk.Frame(shell, bg=_UI["bg"])
    top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    tk.Label(top, text="ScamSentinel", bg=_UI["bg"], fg=_UI["text"], font=title_font).pack(side=tk.LEFT)
    top_btns = tk.Frame(top, bg=_UI["bg"])
    top_btns.pack(side=tk.RIGHT)
    new_chat_btn = tk.Button(top_btns, text="新對話", relief=tk.GROOVE, padx=10, pady=3)
    new_chat_btn.pack(side=tk.LEFT, padx=(0, 6))
    settings_btn = tk.Button(top_btns, text="設定", relief=tk.GROOVE, padx=10, pady=3)
    settings_btn.pack(side=tk.LEFT)

    # —— 對話區 ——
    chat_frame = tk.Frame(shell, bg=_UI["border"], bd=0)
    chat_frame.grid(row=1, column=0, sticky="nsew")
    chat_frame.columnconfigure(0, weight=1)
    chat_frame.rowconfigure(0, weight=1)

    chat = tk.Text(
        chat_frame,
        wrap=tk.WORD,
        state=tk.DISABLED,
        font=ui_font,
        bg=_UI["surface"],
        fg=_UI["text"],
        relief=tk.FLAT,
        padx=16,
        pady=14,
        spacing3=6,
        highlightthickness=0,
        borderwidth=0,
        cursor="arrow",
    )
    chat_scroll = ttk.Scrollbar(chat_frame, command=chat.yview)
    chat.configure(yscrollcommand=chat_scroll.set)
    chat.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
    chat_scroll.grid(row=0, column=1, sticky="ns", pady=1)

    chat.tag_configure("role_user", foreground=_UI["accent"], font=("Segoe UI Semibold", 10))
    chat.tag_configure("role_assistant", foreground=_UI["text"], font=("Segoe UI Semibold", 10))
    chat.tag_configure("role_system", foreground=_UI["muted"], font=("Segoe UI Semibold", 10))
    chat.tag_configure("body", foreground=_UI["text"], lmargin1=4, lmargin2=4)
    chat.tag_configure("body_user", background=_UI["user_bg"], lmargin1=4, lmargin2=4, rmargin=40)
    chat.tag_configure("body_system", foreground=_UI["muted"])

    # —— 狀態列 ——
    busy_var = tk.StringVar(value="")
    status = tk.Label(shell, textvariable=busy_var, bg=_UI["bg"], fg=_UI["busy"], font=small_font, anchor=tk.W)
    status.grid(row=2, column=0, sticky="ew", pady=(6, 4))

    # —— 固定高度輸入列（一定看得到）——
    composer_outer = tk.Frame(shell, bg=_UI["border"], height=110)
    composer_outer.grid(row=3, column=0, sticky="ew")
    composer_outer.grid_propagate(False)
    composer_outer.columnconfigure(0, weight=1)
    composer_outer.rowconfigure(0, weight=1)

    composer = tk.Frame(composer_outer, bg=_UI["input_bg"])
    composer.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
    composer.columnconfigure(0, weight=1)
    composer.rowconfigure(0, weight=1)

    entry = tk.Text(
        composer,
        wrap=tk.WORD,
        font=ui_font,
        bg=_UI["input_bg"],
        fg=_UI["placeholder"],
        insertbackground=_UI["text"],
        relief=tk.FLAT,
        padx=12,
        pady=10,
        height=3,
        highlightthickness=0,
        borderwidth=0,
    )
    entry.grid(row=0, column=0, sticky="nsew")
    entry.insert("1.0", _PLACEHOLDER)
    entry._placeholder_on = True  # type: ignore[attr-defined]

    send_btn = tk.Button(
        composer,
        text="送出",
        bg=_UI["accent"],
        fg="#FFFFFF",
        activebackground=_UI["accent_hover"],
        activeforeground="#FFFFFF",
        relief=tk.FLAT,
        font=("Segoe UI Semibold", 10),
        padx=18,
        pady=8,
        cursor="hand2",
    )
    send_btn.grid(row=0, column=1, padx=(8, 10), pady=10, sticky="e")

    def _clear_placeholder(_e: Any = None) -> None:
        if getattr(entry, "_placeholder_on", False):
            entry.delete("1.0", tk.END)
            entry.configure(fg=_UI["text"])
            entry._placeholder_on = False  # type: ignore[attr-defined]

    def _maybe_restore_placeholder(_e: Any = None) -> None:
        if not entry.get("1.0", tk.END).strip():
            entry.delete("1.0", tk.END)
            entry.configure(fg=_UI["placeholder"])
            entry.insert("1.0", _PLACEHOLDER)
            entry._placeholder_on = True  # type: ignore[attr-defined]

    def _read_entry() -> str:
        if getattr(entry, "_placeholder_on", False):
            return ""
        return entry.get("1.0", tk.END).strip()

    entry.bind("<FocusIn>", _clear_placeholder)
    entry.bind("<FocusOut>", _maybe_restore_placeholder)

    persona_state = _default_persona()
    q: queue.Queue[tuple[str, str | None, dict[str, Any] | None]] = queue.Queue()
    ctx = SkillContext(user_input="")
    session = SessionMemory()
    auto_index = 0
    auto_rows: list[dict[str, Any]] = []
    auto_running = bool(auto_jobs)

    def append_chat(who: str, text: str) -> None:
        role_key = "user" if who in ("你", "User") else ("system" if who in ("系統", "System") else "assistant")
        label = {"user": "你", "assistant": "ScamSentinel", "system": "提示"}[role_key]
        body_tag = "body_user" if role_key == "user" else ("body_system" if role_key == "system" else "body")
        chat.configure(state=tk.NORMAL)
        chat.insert(tk.END, f"{label}\n", f"role_{role_key}")
        chat.insert(tk.END, f"{text}\n\n", body_tag)
        chat.see(tk.END)
        chat.configure(state=tk.DISABLED)

    def reset_session() -> None:
        nonlocal ctx, session
        ctx = SkillContext(user_input="")
        session = SessionMemory()

    def set_sending(busy: bool) -> None:
        send_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
        entry.configure(state=tk.DISABLED if busy else tk.NORMAL)
        if busy:
            busy_var.set("正在回覆…")
        else:
            busy_var.set("")

    def worker(user_message: str, job: dict[str, Any] | None = None) -> None:
        meta: dict[str, Any] | None = None
        try:
            ctx.policy_state["dai_persona"] = _persona_dict_from_state(persona_state)
            cp = build_context_pack_for_turn(
                session,
                user_message,
                user_facts=ctx.policy_state.get("user_facts"),
                pending_memory_confirm=ctx.policy_state.get("pending_memory_confirm"),
            )
            out = run_plan_and_execute(user_text=user_message, ctx=ctx, context_pack=cp)
            result_summary = (
                format_results_for_display(out.results) if out.results else ""
            )
            # 正式介面：只給使用者自然回覆 + DAI 摘要
            face = _build_user_facing_reply(out.answer, out.results)
            memory_answer = face
            plan_detail = " → ".join(f"{s.skill}" for s in out.plan) or ""
            meta = {
                "scenario_id": (job or {}).get("scenario_id", "manual"),
                "ref": (job or {}).get("ref", "手動"),
                "user": user_message,
                "task_type": out.task_type,
                "plan": plan_detail,
                "pending_review": bool(ctx.policy_state.get("pending_review")),
                "answer": face[:200],
            }
            q.put(("assistant", face, meta))
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
            q.put(("assistant", "抱歉，處理時發生問題，請稍後再試。", meta))
            # 細節只寫 log，不上畫面
            log.error("desktop error: %s", e)

    def start_auto_turn() -> None:
        nonlocal auto_index, auto_running
        if auto_index >= len(auto_jobs):
            auto_running = False
            reset_session()
            out_path = _write_auto_dialogue(args.auto_problem or "", auto_rows)
            set_sending(False)
            append_chat("系統", f"自動測試完成（{len(auto_rows)} 輪）。")
            log.info("auto dialogue written: %s", out_path)
            return
        job = auto_jobs[auto_index]
        if job.get("fresh_session"):
            reset_session()
        user_text = str(job["user"])
        append_chat("你", user_text)
        set_sending(True)
        busy_var.set(f"自動測試 {auto_index + 1}/{len(auto_jobs)}…")
        threading.Thread(target=worker, args=(user_text, job), daemon=True).start()

    def on_send(_e: Any = None) -> str | None:
        if auto_running:
            return "break"
        raw = _read_entry()
        if not raw:
            return "break"
        append_chat("你", raw)
        entry.delete("1.0", tk.END)
        entry._placeholder_on = False  # type: ignore[attr-defined]
        entry.configure(fg=_UI["text"])
        set_sending(True)
        threading.Thread(target=worker, args=(raw, None), daemon=True).start()
        return "break"

    def poll_queue() -> None:
        nonlocal auto_index, auto_running
        try:
            while True:
                role, text, meta = q.get_nowait()
                if role == "assistant":
                    append_chat("助理", text or "")
                    if meta:
                        auto_rows.append(meta)
                    if auto_running:
                        auto_index += 1
                        root.after(600, start_auto_turn)
                    else:
                        set_sending(False)
                        _maybe_restore_placeholder()
                        entry.focus_set()
        except queue.Empty:
            pass
        root.after(120, poll_queue)

    def on_new_chat() -> None:
        if auto_running:
            return
        reset_session()
        chat.configure(state=tk.NORMAL)
        chat.delete("1.0", tk.END)
        chat.configure(state=tk.DISABLED)
        append_chat("系統", "已開始新對話。直接輸入或貼上簡訊即可。")
        entry.focus_set()
        _clear_placeholder()

    send_btn.configure(command=on_send)
    new_chat_btn.configure(command=on_new_chat)
    settings_btn.configure(command=lambda: _open_settings_dialog(root, persona_state))
    entry.bind("<Control-Return>", on_send)

    if auto_jobs:
        append_chat("系統", "正在執行自動測試…")
        set_sending(True)
    else:
        append_chat(
            "系統",
            "你好，我是 ScamSentinel。\n"
            "貼上可疑簡訊，或直接問我問題。\n"
            "右上角「設定」可調整個人情境（可選）。",
        )
        root.after(200, entry.focus_set)

    poll_queue()
    if auto_jobs:
        root.after(800, start_auto_turn)
    root.mainloop()


if __name__ == "__main__":
    main()
