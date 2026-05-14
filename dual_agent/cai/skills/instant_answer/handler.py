from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from dual_agent.skill_types import SkillContext, SkillResult

_USER_AGENT = "curl/8.4.0 (compatible; Dual-agent/instant_answer)"

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "要查的短語"}},
    "required": ["query"],
}


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    q = (args.get("query") or args.get("q") or "").strip()
    if not q:
        return SkillResult(ok=False, skill="instant_answer", summary="缺少 query", error="missing_query")

    params = urllib.parse.urlencode(
        {"q": q, "format": "json", "no_html": "1", "skip_disambig": "1"}
    )
    url = f"https://api.duckduckgo.com/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(400_000)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="instant_answer",
            summary=f"DuckDuckGo API 請求失敗：{e}",
            data={"query": q},
            error=str(e),
        )

    try:
        obj = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        return SkillResult(
            ok=False,
            skill="instant_answer",
            summary="回應非有效 JSON",
            data={"query": q},
            error=str(e),
        )

    heading = (obj.get("Heading") or "").strip()
    abstract = (obj.get("AbstractText") or obj.get("Abstract") or "").strip()
    src_url = (obj.get("AbstractURL") or "").strip()
    answer_type = (obj.get("AnswerType") or "").strip()
    answer = (obj.get("Answer") or "").strip()

    lines: list[str] = []
    if heading:
        lines.append(f"標題：{heading}")
    if answer and not abstract:
        lines.append(answer)
    if abstract:
        lines.append(abstract)
    if src_url:
        lines.append(f"來源：{src_url}")
    text = "\n".join(lines).strip()

    if not text:
        return SkillResult(
            ok=True,
            skill="instant_answer",
            summary="（無即時摘要；可改 search_web 或換關鍵字）",
            data={
                "query": q,
                "heading": heading,
                "abstract": abstract,
                "abstract_url": src_url,
                "answer_type": answer_type,
                "instant_empty": True,
            },
        )

    summary_line = (abstract or answer or heading or text)[:280]
    return SkillResult(
        ok=True,
        skill="instant_answer",
        summary=summary_line,
        data={
            "query": q,
            "heading": heading,
            "abstract": abstract,
            "abstract_url": src_url,
            "answer_type": answer_type,
            "text": text[:8000],
        },
    )
