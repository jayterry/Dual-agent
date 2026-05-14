"""url_guard 與 fetch_url skill。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from dual_agent.cai.executor import format_results_for_display
from dual_agent.skill_types import SkillContext, SkillResult
from dual_agent.cai.skills.fetch_url.handler import handle as fetch_handle
from dual_agent.cai.url_guard import validate_public_http_url


def test_validate_blocks_loopback_hostname() -> None:
    ok, err = validate_public_http_url("http://127.0.0.1/")
    assert ok is False
    assert "blocked" in err


def test_validate_blocks_literal_private() -> None:
    ok, err = validate_public_http_url("http://192.168.1.1/")
    assert ok is False


def test_fetch_url_ok_plain_text() -> None:
    body = b"Hello world content"
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.geturl.return_value = "https://example.com/doc"
    mock_resp.headers.get_content_type.return_value = "text/plain"
    mock_resp.headers.get_content_charset.return_value = "utf-8"
    ctx = SkillContext(user_input="")
    with patch("dual_agent.cai.skills.fetch_url.handler.validate_public_http_url", return_value=(True, "")):
        with patch("urllib.request.OpenerDirector.open", return_value=mock_resp):
            r = fetch_handle({"url": "https://example.com/doc"}, ctx)
    assert r.ok
    assert "Hello world" in (r.data.get("text") or "")


def test_format_results_includes_fetch_body() -> None:
    r = SkillResult(
        ok=True,
        skill="fetch_url",
        summary="已抓取 12 字",
        data={"text": "正文在這裡一二三四五六七八九十", "url": "https://a"},
    )
    out = format_results_for_display([r])
    assert "抓取正文" in out
    assert "正文在這裡" in out
