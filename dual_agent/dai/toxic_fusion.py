"""毒樣 JSON 向量比對與可設定權重之風險融合（Dual-agent 內建；不讀取倉庫外路徑）。"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from langchain_ollama import OllamaEmbeddings

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL

log = logging.getLogger(__name__)


def ollama_embed_model() -> str:
    v = os.environ.get("OLLAMA_EMBED_MODEL", "").strip()
    return v or OLLAMA_MODEL


@dataclass(frozen=True)
class ToxicMatch:
    max_cosine: float
    best_id: Optional[str]
    s_tox_0_100: int
    embed_dim: int
    toxic_count: int


@dataclass(frozen=True)
class FusedRisk:
    r_llm_0_100: int
    s_tox_0_100: int
    risk_total_0_100: int


def canonicalize_sms_for_toxic(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return ""
    t = re.sub(r"https?://\S+", "[URL]", t, flags=re.IGNORECASE)
    t = re.sub(r"\bwww\.\S+", "[URL]", t, flags=re.IGNORECASE)
    t = re.sub(r"(?:\+886|0)?9\d{8}", "[PHONE]", t)
    t = re.sub(r"\b\d{4,6}\b", "[NUM]", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _l2_norm(v: list[float]) -> float:
    return float(math.sqrt(sum(x * x for x in v)))


def _cosine_sim(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    for x, y in zip(a, b, strict=True):
        dot += float(x) * float(y)
    na = _l2_norm(a)
    nb = _l2_norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    v = dot / (na * nb)
    return float(max(-1.0, min(1.0, v)))


def _as_float_list(x: Any) -> list[float]:
    if not isinstance(x, list):
        return []
    out: list[float] = []
    for it in x:
        try:
            out.append(float(it))
        except Exception:
            return []
    return out


def load_toxic_entries(path: str) -> list[dict[str, Any]]:
    p = (path or "").strip()
    if not p:
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        log.warning("Toxic DB 檔案不存在，略過 path=%s", p)
        return []
    except Exception as e:  # noqa: BLE001
        log.error("讀取 Toxic DB 失敗 path=%s err=%s", p, e)
        return []

    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        return [x for x in data["items"] if isinstance(x, dict)]
    return []


_EMB: OllamaEmbeddings | None = None


def _get_embedder() -> OllamaEmbeddings:
    global _EMB
    if _EMB is None:
        _EMB = OllamaEmbeddings(
            model=ollama_embed_model(),
            base_url=OLLAMA_BASE_URL,
        )
    return _EMB


def embed_text(text: str) -> list[float]:
    emb = _get_embedder()
    v = emb.embed_query(text)
    if not isinstance(v, list):
        return _as_float_list(list(v))  # type: ignore[arg-type]
    return _as_float_list(v)


def s_tox_from_max_cosine(max_cos: float) -> int:
    tau = float(os.environ.get("TOXIC_COS_TAU", "0.55"))
    gamma = float(os.environ.get("TOXIC_COS_GAMMA", "2.0"))
    x = max(0.0, float(max_cos) - tau) / max(1e-6, 1.0 - tau)
    if gamma != 1.0:
        x = x**gamma
    return int(max(0, min(100, round(100.0 * x))))


def match_toxic(*, raw_sms: str, toxic_path: str) -> ToxicMatch:
    entries = load_toxic_entries(toxic_path)
    if not entries:
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)

    canon = canonicalize_sms_for_toxic(raw_sms)
    v_new = embed_text(canon)
    if not v_new:
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=len(entries))

    best_sim = -1.0
    best_id: Optional[str] = None
    for e in entries:
        ev = e.get("embedding_vector")
        vec = _as_float_list(ev) if isinstance(ev, list) else []
        if not vec:
            continue
        if len(vec) != len(v_new):
            continue
        s = _cosine_sim(v_new, vec)
        if s > best_sim:
            best_sim = s
            best_id = str(e.get("id") or "")

    if best_sim < 0.0:
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=len(v_new), toxic_count=len(entries))

    stox = s_tox_from_max_cosine(best_sim)
    return ToxicMatch(
        max_cosine=float(best_sim),
        best_id=best_id or None,
        s_tox_0_100=int(stox),
        embed_dim=len(v_new),
        toxic_count=len(entries),
    )


def fuse_risk(*, r_llm_0_100: int, s_tox_0_100: int) -> FusedRisk:
    w_llm = float(os.environ.get("FUSED_RISK_W_LLM", "0.75"))
    w_tox = float(os.environ.get("FUSED_RISK_W_TOX", "0.25"))
    b = float(os.environ.get("FUSED_RISK_BIAS", "0.0"))
    total = w_llm * float(r_llm_0_100) + w_tox * float(s_tox_0_100) - b
    total_i = int(max(0, min(100, round(total))))
    return FusedRisk(r_llm_0_100=int(r_llm_0_100), s_tox_0_100=int(s_tox_0_100), risk_total_0_100=total_i)
