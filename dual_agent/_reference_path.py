


"""
將同層參考專案 Dual-LLM-main 加入 sys.path，以便重用其 Plan & Execute CAI 引擎。

里程碑一刻意不實作 flow.md 的 Memory／Context Pack 模組；參考引擎內建的
SkillContext／state_capsule 仍會隨回合更新（與正式規格的「CAI 記憶層」分開）。
"""

from __future__ import annotations

import sys
from pathlib import Path


def dual_agent_root() -> Path:
    return Path(__file__).resolve().parent.parent


def dual_llm_main_path() -> Path:
    return dual_agent_root().parent / "Dual-LLM-main"


def ensure_dual_llm_on_path() -> Path:
    p = dual_llm_main_path()
    if p.is_dir():
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return p
