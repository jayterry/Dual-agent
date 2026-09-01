"""Ollama HTTP 用戶端（stdlib，無額外依賴）。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class OllamaConfig:
    host: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b"
    timeout_s: float = 120.0
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> OllamaConfig:
        return cls(
            host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
            model=os.environ.get("OLLAMA_MODEL", "qwen2.5:7b"),
            timeout_s=float(os.environ.get("PATH_B_TIMEOUT", "120")),
            temperature=float(os.environ.get("PATH_B_TEMPERATURE", "0.1")),
        )


class OllamaError(RuntimeError):
    pass


def _post_chat(body: dict, *, host: str, timeout_s: float) -> str:
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise OllamaError(f"Ollama HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise OllamaError(f"Ollama unreachable at {host}: {e}") from e
    except TimeoutError as e:
        raise OllamaError(f"Ollama timeout after {timeout_s}s") from e

    try:
        data = json.loads(raw)
        content = data["message"]["content"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise OllamaError(f"Unexpected Ollama response: {raw[:400]}") from e
    if not isinstance(content, str) or not content.strip():
        raise OllamaError("Ollama returned empty content")
    return content.strip()


def chat_text(
    *,
    system: str,
    user: str,
    config: OllamaConfig | None = None,
) -> str:
    """呼叫 /api/chat，回傳純文字（不強制 JSON）。"""
    cfg = config or OllamaConfig.from_env()
    body = {
        "model": cfg.model,
        "stream": False,
        "options": {"temperature": cfg.temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    return _post_chat(body, host=cfg.host, timeout_s=cfg.timeout_s)


def chat_json(
    *,
    system: str,
    user: str,
    config: OllamaConfig | None = None,
) -> str:
    """呼叫 /api/chat，要求 JSON 格式回覆；回傳 message.content 字串。"""
    cfg = config or OllamaConfig.from_env()
    body = {
        "model": cfg.model,
        "stream": False,
        "format": "json",
        "options": {"temperature": cfg.temperature},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    return _post_chat(body, host=cfg.host, timeout_s=cfg.timeout_s)

