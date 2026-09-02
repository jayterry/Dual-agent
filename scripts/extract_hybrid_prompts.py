"""一次性：自 docs/Hybrid-Prompt-Drafts.md 抽出 prompt 檔。"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "docs" / "Hybrid-Prompt-Drafts.md"
OUT = ROOT / "dual_agent" / "cai" / "hybrid" / "prompts"

SECTIONS = {
    "nlp_system.txt": r"## NLP System — `nlp_system\.txt`\s*\n\n```text\n(.*?)```",
    "planner_system.txt": r"## Planner System — `planner_system\.txt`\s*\n\n```text\n(.*?)```",
    "react_replan_system.txt": r"## ReAct Replan System — `react_replan_system\.txt`\s*\n\n```text\n(.*?)```",
}


def main() -> None:
    text = DRAFTS.read_text(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fewshots").mkdir(exist_ok=True)
    for fname, pat in SECTIONS.items():
        m = re.search(pat, text, re.DOTALL)
        if not m:
            raise SystemExit(f"missing section: {fname}")
        (OUT / fname).write_text(m.group(1).strip() + "\n", encoding="utf-8")
    jm = re.search(
        r"## Few-shots — `fewshots/message_features\.json`\s*\n\n```json\n(.*?)```",
        text,
        re.DOTALL,
    )
    if not jm:
        raise SystemExit("missing fewshots json")
    raw = jm.group(1).strip()
    data = json.loads(raw)
    # 修正簡繁混用
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    blob = blob.replace("请立即", "請立即")
    (OUT / "fewshots" / "message_features.json").write_text(blob + "\n", encoding="utf-8")
    print("ok:", OUT)


if __name__ == "__main__":
    main()
