from __future__ import annotations

import json
import re
import ssl
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from dual_agent.skill_types import SkillContext, SkillResult
from dual_agent.cai.url_guard import validate_public_http_url

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string", "description": "https? 公開網址"},
        "max_chars": {"type": "integer", "description": "輸出文字上限，預設 12000"},
    },
    "required": ["url"],
}

_USER_AGENT = "Mozilla/5.0 (compatible; Dual-agent/fetch_url; +https://github.com/)"
_MAX_DOWNLOAD_BYTES = 900_000
_MAX_REDIRECTS = 6


class _StripHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        chunk = (data or "").strip()
        if chunk:
            self._chunks.append(chunk)

    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


class _GuardedRedirectHandler(HTTPRedirectHandler):
    """每次轉址都重新驗證目標 URL（防 SSRF 跳轉到內網）。"""

    def __init__(self) -> None:
        super().__init__()
        self._count = 0

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:  # noqa: ARG002
        self._count += 1
        if self._count > _MAX_REDIRECTS:
            return None
        abs_url = urljoin(req.full_url, newurl)
        ok, err = validate_public_http_url(abs_url)
        if not ok:
            raise URLError(f"blocked_redirect:{err}:{abs_url}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _decode_body(raw: bytes, content_type: str | None, charset_hint: str | None = None) -> str:
    charset = charset_hint
    if not charset and content_type:
        m = re.search(r"charset=([\w-]+)", content_type, re.I)
        if m:
            charset = m.group(1).strip().strip('"').lower()
    for enc in (charset, "utf-8", "utf-8-sig", "latin-1"):
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    p = _StripHTML()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)
    return p.text()


def _body_to_text(body: str, content_type: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if "json" in ct:
        try:
            obj = json.loads(body)
            return json.dumps(obj, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return body
    if "html" in ct or body.lstrip().lower().startswith("<!doctype html") or "<html" in body[:2000].lower():
        return _html_to_text(body)
    return body.strip()


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:  # noqa: ARG001
    url = (args.get("url") or args.get("href") or "").strip()
    if not url:
        return SkillResult(ok=False, skill="fetch_url", summary="缺少 url", error="missing_url")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return SkillResult(ok=False, skill="fetch_url", summary="僅允許 http/https", error="bad_scheme")

    ok, err = validate_public_http_url(url)
    if not ok:
        return SkillResult(
            ok=False,
            skill="fetch_url",
            summary=f"網址未通過安全檢查：{err}",
            data={"url": url},
            error=err,
        )

    max_chars = args.get("max_chars")
    try:
        cap = int(max_chars) if max_chars is not None else 12_000
    except (TypeError, ValueError):
        cap = 12_000
    cap = max(500, min(cap, 80_000))

    opener = build_opener(_GuardedRedirectHandler())
    req = Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,text/plain;q=0.8,*/*;q=0.5",
            "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
        },
        method="GET",
    )
    ctx_ssl = ssl.create_default_context()
    try:
        resp = opener.open(req, timeout=25, context=ctx_ssl)  # type: ignore[call-arg]
    except HTTPError as e:
        return SkillResult(
            ok=False,
            skill="fetch_url",
            summary=f"HTTP {e.code}",
            data={"url": url, "final_url": getattr(e, "url", url)},
            error=e.reason or str(e.code),
        )
    except URLError as e:
        return SkillResult(
            ok=False,
            skill="fetch_url",
            summary=f"請求失敗：{e.reason!s}",
            data={"url": url},
            error=str(e.reason),
        )
    except Exception as e:  # noqa: BLE001
        return SkillResult(ok=False, skill="fetch_url", summary=f"請求異常：{e}", data={"url": url}, error=str(e))

    try:
        raw = resp.read(_MAX_DOWNLOAD_BYTES + 1)
        final_url = resp.geturl() or url
        if hasattr(resp.headers, "get_content_type"):
            ctype = resp.headers.get_content_type()
        else:
            ctype = resp.headers.get("Content-Type")
        charset_hint = None
        if hasattr(resp.headers, "get_content_charset"):
            charset_hint = resp.headers.get_content_charset()
    finally:
        resp.close()

    if len(raw) > _MAX_DOWNLOAD_BYTES:
        raw = raw[:_MAX_DOWNLOAD_BYTES]

    ok2, err2 = validate_public_http_url(final_url)
    if not ok2:
        return SkillResult(
            ok=False,
            skill="fetch_url",
            summary=f"最終網址未通過安全檢查：{err2}",
            data={"url": url, "final_url": final_url},
            error=err2,
        )

    text = _decode_body(raw, ctype, charset_hint)
    plain = _body_to_text(text, ctype)
    if len(plain) > cap:
        plain = plain[:cap] + "\n…（已依 max_chars 截斷）"

    snippet = plain[:400].replace("\n", " ")
    summary = f"已抓取 {len(plain)} 字 · {snippet}…" if len(plain) > 400 else f"已抓取 {len(plain)} 字 · {snippet}"

    return SkillResult(
        ok=True,
        skill="fetch_url",
        summary=summary,
        data={
            "url": url,
            "final_url": final_url,
            "content_type": ctype or "",
            "char_count": len(plain),
            "text": plain,
        },
    )
