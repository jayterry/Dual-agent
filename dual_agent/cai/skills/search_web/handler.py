from __future__ import annotations

import webbrowser
from typing import Any
from urllib.parse import quote_plus

from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜尋字串"},
        "engine": {"type": "string", "enum": ["bing", "google", "duckduckgo"]},
    },
    "required": ["query"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return SkillResult(ok=False, skill="search_web", summary="缺少 query 參數", error="missing_query")
    engine = (args.get("engine") or "bing").strip().lower()
    if engine not in ("bing", "google", "duckduckgo"):
        engine = "bing"
    if engine == "google":
        url = f"https://www.google.com/search?q={quote_plus(query)}"
    elif engine == "duckduckgo":
        url = f"https://duckduckgo.com/?q={quote_plus(query)}"
    else:
        url = f"https://www.bing.com/search?q={quote_plus(query)}"
    try:
        webbrowser.open(url, new=2)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="search_web",
            summary=f"無法開啟瀏覽器：{e}",
            data={"url": url, "engine": engine, "query": query},
            error=str(e),
        )
    return SkillResult(ok=True, skill="search_web", summary=f"已開啟搜尋：{query}", data={"url": url, "engine": engine})

