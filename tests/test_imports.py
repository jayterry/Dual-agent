"""確保 dual_agent 可匯入且技能目錄存在。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dual_agent.skills_registry import SKILLS, get_tool_catalog


def test_skills_loaded() -> None:
    assert "open_url_readonly" in SKILLS or "search_web" in SKILLS
    assert "run_guard_pipeline" in SKILLS
    assert "call_dai" in SKILLS
    cat = get_tool_catalog()
    assert isinstance(cat, list)
    assert len(cat) >= 1


def test_skills_dir_layout() -> None:
    root = Path(__file__).resolve().parents[1] / "dual_agent" / "cai" / "skills"
    assert (root / "ask_user" / "handler.py").is_file()


@pytest.mark.skip(reason="需本機 Ollama；僅手動或 CI 有服務時啟用")
def test_run_plan_smoke() -> None:
    from dual_agent.cai.plan_execute import run_plan_and_execute
    from dual_agent.skill_types import SkillContext

    out = run_plan_and_execute(user_text="你好", ctx=SkillContext(user_input=""))
    assert out.answer
