from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from dual_agent.skill_types import SkillContext, SkillResult

# wttr.in 建議帶類 curl User-Agent，避免被預設 Python UA 擋下
_USER_AGENT = "curl/8.4.0 (compatible; Dual-agent/weather; wttr.in)"

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "location": {"type": "string", "description": "城市、地區或機場代碼"},
        "format": {"type": "string", "enum": ["brief", "json"], "description": "brief=單行；json=結構化摘要"},
    },
    "required": ["location"],
}


def _fetch_wttr(path_segment: str, query: str) -> tuple[bool, str, bytes]:
    url = f"https://wttr.in/{path_segment}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return True, url, resp.read(600_000)
    except urllib.error.HTTPError as e:
        return False, url, (e.read(32_000) or str(e).encode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        return False, url, str(e).encode("utf-8", errors="replace")


def _json_summary(blob: bytes) -> str:
    obj = json.loads(blob.decode("utf-8", errors="replace"))
    parts: list[str] = []
    cur = (obj.get("current_condition") or [{}])[0]
    if cur:
        parts.append(
            f"目前：{cur.get('weatherDesc', [{}])[0].get('value', '?')} "
            f"氣溫 {cur.get('temp_C', '?')}°C 體感 {cur.get('FeelsLikeC', '?')}°C "
            f"濕度 {cur.get('humidity', '?')}% 風速 {cur.get('windspeedKmph', '?')} km/h"
        )
    loc = obj.get("nearest_area") or []
    if loc and isinstance(loc[0], dict):
        a = loc[0]
        name = (a.get("areaName") or [{}])[0].get("value", "")
        country = (a.get("country") or [{}])[0].get("value", "")
        if name:
            parts.insert(0, f"地點：{name}" + (f", {country}" if country else ""))
    wx = obj.get("weather") or []
    if wx and isinstance(wx[0], dict):
        w0 = wx[0]
        parts.append(f"今日：最高 {w0.get('maxtempC', '?')}°C 最低 {w0.get('mintempC', '?')}°C")
    return "\n".join(parts) if parts else blob.decode("utf-8", errors="replace")[:2000]


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    loc = (args.get("location") or args.get("city") or args.get("place") or "").strip()
    if not loc:
        return SkillResult(ok=False, skill="weather", summary="缺少 location", error="missing_location")
    fmt = (args.get("format") or "brief").strip().lower()
    if fmt not in ("brief", "json"):
        fmt = "brief"

    # wttr 以 path 表示地點；空白與 UTF-8 地名需編碼
    path_seg = urllib.parse.quote(loc, safe="")
    query = "format=j1" if fmt == "json" else "format=3&m"
    ok, url, body = _fetch_wttr(path_seg, query)
    if not ok:
        err = body.decode("utf-8", errors="replace")[:800]
        return SkillResult(
            ok=False,
            skill="weather",
            summary=f"wttr.in 請求失敗：{err[:200]}",
            data={"url": url, "location": loc, "format": fmt},
            error=err[:500],
        )

    if fmt == "json":
        try:
            text = _json_summary(body)
        except Exception as e:  # noqa: BLE001
            text = body.decode("utf-8", errors="replace")[:4000]
            return SkillResult(
                ok=True,
                skill="weather",
                summary=f"已取得天氣 JSON（解析部分失敗：{e}）",
                data={"url": url, "location": loc, "format": fmt, "text": text, "raw_excerpt": text[:1200]},
            )
        return SkillResult(
            ok=True,
            skill="weather",
            summary=text.split("\n", 1)[0][:240] if text else "已取得天氣",
            data={"url": url, "location": loc, "format": fmt, "text": text},
        )

    line = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
    return SkillResult(
        ok=True,
        skill="weather",
        summary=line[:300] if line else "已取得天氣",
        data={"url": url, "location": loc, "format": fmt, "text": line},
    )
