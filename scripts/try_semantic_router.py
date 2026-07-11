#!/usr/bin/env python3
"""手動試跑 semantic_router（不需 Ollama）。用法：py scripts/try_semantic_router.py \"你的句子\""""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dual_agent.cai.semantic_router import route_user_text  # noqa: E402


def main() -> None:
    text = " ".join(sys.argv[1:]).strip() or "搜尋台北天氣，再開 https://github.com"
    r = route_user_text(text)
    out = {
        "input": text,
        "confidence": r.confidence,
        "task_type": r.task_type,
        "task_state": r.task_state,
        "reason_codes": r.reason_codes,
        "todos": [{"skill": s.skill, "args": s.args} for s in r.todos],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
