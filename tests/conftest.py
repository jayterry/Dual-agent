"""pytest 共用設定：預設關閉 Hybrid，避免需 Ollama 的 NLP 路徑影響舊測試。"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_hybrid_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("CAI_HYBRID_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        return
    monkeypatch.setenv("CAI_HYBRID_ENABLED", "false")


@pytest.fixture(autouse=True)
def _skip_memory_llm_in_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """避免 plan_execute 測試誤觸 Ollama Memory LLM；memory 專測除外。"""
    node_path = str(getattr(request.node, "fspath", "") or "")
    if "test_memory" in node_path:
        return
    monkeypatch.setattr(
        "dual_agent.cai.plan_execute.try_handle_memory_turn",
        lambda *args, **kwargs: None,
    )
