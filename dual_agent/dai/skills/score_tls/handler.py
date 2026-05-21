from __future__ import annotations

from typing import Any

from dual_agent.dai.skills._skill_handler_factory import make_dai_step_handler

ARGS_SCHEMA: dict[str, Any] = {}

handle = make_dai_step_handler("score_tls")
