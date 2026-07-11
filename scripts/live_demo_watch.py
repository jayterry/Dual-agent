#!/usr/bin/env python3
"""即時 Ollama 對話示範：終端機印出每輪，並同步寫入 test_dialogue。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.cai.plan_execute import run_plan_and_execute
from dual_agent.skill_types import SkillContext

TZ8 = timezone(timedelta(hours=8))


def main() -> int:
    turns = [
        "你好",
        "我收到一則簡訊",
        "我沒有要你看簡訊",
        "台灣台中市明天的天氣",
    ]
    now = datetime.now(TZ8)
    out_dir = _ROOT / "test_dialogue" / "agent_full_coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{now.strftime('%Y-%m-%d_即時Ollama示範')}.md"

    lines = [
        "# 即時示範：測試者 ↔ Dual-agent（Ollama）",
        "",
        f"| 時間 | {now.strftime('%Y-%m-%d %H:%M')} (UTC+8) |",
        "| 環境 | 真實 Ollama Planner/Replan |",
        "",
    ]

    ctx = SkillContext(user_input="")
    print("=" * 60)
    print("即時 Ollama 對話（請看 Terminal）")
    print("=" * 60, flush=True)

    for i, user in enumerate(turns, 1):
        print(f"\n>>> 第 {i} 輪", flush=True)
        print(f"【測試者】 {user}", flush=True)
        print("（Dual-agent 思考中…）", flush=True)
        out = run_plan_and_execute(user_text=user, ctx=ctx)
        plan = " → ".join(f"{s.skill} {dict(s.args or {})}" for s in out.plan) or "（空）"
        pr = bool(ctx.policy_state.get("pending_review"))
        ans = (out.answer or "").replace("\n", " ")
        print(f"【計畫】 {plan}", flush=True)
        print(f"【狀態】 {out.task_type} / {out.task_state} | pending_review={pr}", flush=True)
        print(f"【Dual-agent】 {ans[:500]}", flush=True)
        lines.extend(
            [
                f"## 第 {i} 輪",
                "",
                f"**測試者**：{user}",
                "",
                f"- 計畫：{plan}",
                f"- task：{out.task_type} / {out.task_state}",
                f"- pending_review：{pr}",
                "",
                f"**Dual-agent**：{ans}",
                "",
            ]
        )
        out_path.write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"已寫入：{out_path}")
    print("=" * 60, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
