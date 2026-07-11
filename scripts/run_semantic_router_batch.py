#!/usr/bin/env python3
"""批次試跑 semantic_router，輸出對照表（不需 Ollama）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.cai.semantic_router import route_user_text  # noqa: E402

BATCH: list[tuple[str, str]] = [
    ("複合：天氣+開URL（Phase 0）", "搜尋台北天氣，再開 https://github.com"),
    ("複合：今天天氣+開URL", "搜尋台北今天天氣，再幫我開 https://github.com"),
    ("複合：天氣+YouTube", "查台北天氣然後開 youtube"),
    ("複合：三任務", "查台北天氣，搜尋台積電股價，再開 youtube"),
    ("複合：搜尋+開URL", "搜尋 Python 教學，再開 https://python.org"),
    ("單一：高雄下雨", "查高雄明天會不會下雨"),
    ("單一：台中天氣", "查詢台中即時天氣"),
    ("單一：台北天氣如何", "台北今天天氣如何"),
    ("單一：Google搜股價", "用 Google 搜台積電股價"),
    ("單一：開GitHub", "打開 https://github.com"),
    ("單一：開google", "打開google"),
    ("單一：讀網頁摘要", "讀 https://example.com 幫我摘要"),
    ("單一：讀URL內容", "讀 https://news.ycombinator.com 內容"),
    ("審查：詐騙URL", "幫我看這是不是詐騙：https://x.com"),
    ("假設：簡訊連結", "打開這則簡訊連結會怎樣"),
    ("假設：惡意URL", "打開 https://evil.example/phish 會怎樣"),
    ("模糊：官網", "用 Google 搜台積電，再開官網"),
    ("指涉：喜歡的遊戲", "搜尋我喜歡的遊戲"),
    ("閒聊：介紹遊戲", "介紹英雄聯盟"),
    ("邊界：google搜天氣", "用google搜天氣"),
    ("邊界：僅宣告簡訊", "我收到一則簡訊"),
]


def main() -> None:
    rows: list[dict] = []
    for label, text in BATCH:
        r = route_user_text(text)
        rows.append(
            {
                "label": label,
                "input": text,
                "confidence": r.confidence,
                "task_type": r.task_type,
                "reason_codes": r.reason_codes,
                "todos": [{"skill": s.skill, "args": s.args} for s in r.todos],
            }
        )
    out_path = _ROOT / "data" / "semantic_router_batch_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    for row in rows:
        skills = " → ".join(t["skill"] for t in row["todos"]) or "(無 todos)"
        print(f"[{row['confidence']}] {row['label']}: {skills}")


if __name__ == "__main__":
    main()
