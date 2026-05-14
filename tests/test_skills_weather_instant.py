"""weather / instant_answer：以 mock 避免依賴外網穩定性。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from dual_agent.skill_types import SkillContext
from dual_agent.cai.skills.instant_answer.handler import handle as instant_handle
from dual_agent.cai.skills.weather.handler import handle as weather_handle


def test_weather_brief_ok() -> None:
    body = b"London: +12C\n"
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    ctx = SkillContext(user_input="")
    with patch("urllib.request.urlopen", return_value=mock_cm):
        r = weather_handle({"location": "London", "format": "brief"}, ctx)
    assert r.ok
    assert "London" in (r.data.get("text") or r.summary)


def test_weather_json_summary_ok() -> None:
    payload = {
        "current_condition": [
            {
                "temp_C": "10",
                "FeelsLikeC": "8",
                "humidity": "70",
                "windspeedKmph": "20",
                "weatherDesc": [{"value": "Cloudy"}],
            }
        ],
        "nearest_area": [
            {
                "areaName": [{"value": "Reykjavik"}],
                "country": [{"value": "Iceland"}],
            }
        ],
        "weather": [{"maxtempC": "11", "mintempC": "5", "hourly": [{}]}],
    }
    raw = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    ctx = SkillContext(user_input="")
    with patch("urllib.request.urlopen", return_value=mock_cm):
        r = weather_handle({"location": "Reykjavik", "format": "json"}, ctx)
    assert r.ok
    assert "Cloudy" in (r.data.get("text") or "")


def test_instant_answer_with_abstract() -> None:
    payload = {
        "Heading": "Python",
        "AbstractText": "A programming language.",
        "AbstractURL": "https://example.com/python",
    }
    raw = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    ctx = SkillContext(user_input="")
    with patch("urllib.request.urlopen", return_value=mock_cm):
        r = instant_handle({"query": "Python programming language"}, ctx)
    assert r.ok
    assert "programming" in r.summary.lower() or "programming" in (r.data.get("abstract") or "").lower()


def test_instant_answer_empty() -> None:
    payload = {"Heading": "", "AbstractText": "", "AbstractURL": ""}
    raw = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = raw
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_resp
    ctx = SkillContext(user_input="")
    with patch("urllib.request.urlopen", return_value=mock_cm):
        r = instant_handle({"query": "zzzznonexistentterm12345"}, ctx)
    assert r.ok
    assert r.data.get("instant_empty") is True
