from __future__ import annotations

import webbrowser
from typing import Any
from urllib.parse import urlparse

from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"url": {"type": "string", "description": "http/https 網址或網站別名"}},
    "required": ["url"],
}

_SITE_ALIASES: dict[str, str] = {
    "github": "https://github.com/",
    "github.com": "https://github.com/",
    "youtube": "https://www.youtube.com/",
    "youtube.com": "https://www.youtube.com/",
    "www.youtube.com": "https://www.youtube.com/",
}


def _is_safe_http_url(url: str) -> bool:
    u = url.strip()
    parsed = urlparse(u)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc or u.startswith("http"))


def _resolve_site_or_url(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    key = t.lower()
    mapped = _SITE_ALIASES.get(key, t)
    mapped = (mapped or "").strip()
    if not mapped:
        return ""
    # 裸網域/host（例如 example.com）自動補 https://
    parsed = urlparse(mapped)
    if not parsed.scheme and "." in mapped and " " not in mapped and not mapped.startswith("//"):
        return f"https://{mapped}"
    return mapped


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    url = _resolve_site_or_url((args.get("url") or args.get("href") or "").strip())
    if not url:
        return SkillResult(ok=False, skill="open_url_readonly", summary="缺少 url 參數", error="missing_url")
    if not _is_safe_http_url(url):
        return SkillResult(
            ok=False,
            skill="open_url_readonly",
            summary="僅允許 http/https 且需有效網址",
            data={"url": url},
            error="invalid_url",
        )
    try:
        webbrowser.open(url, new=2)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="open_url_readonly",
            summary=f"無法開啟瀏覽器：{e}",
            data={"url": url},
            error=str(e),
        )
    return SkillResult(ok=True, skill="open_url_readonly", summary=f"已嘗試開啟：{url}", data={"url": url})

