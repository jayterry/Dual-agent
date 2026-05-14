"""可選：以既有 Chroma 持久化目錄做毒樣相似度（需 collection 內已向量化）。"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from dual_agent.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from dual_agent.dai.toxic_fusion import ToxicMatch, canonicalize_sms_for_toxic, s_tox_from_max_cosine

log = logging.getLogger(__name__)


def _score_to_cosine_similarity(score: float) -> float:
    """
    LangChain Chroma 回傳的 score 依後端版本可能是 distance 或 similarity。
    保守轉成 [0,1] 的「越高越像」值供 s_tox_from_max_cosine 使用。
    """
    s = float(score)
    if s != s:  # NaN
        return 0.0
    if 0.0 <= s <= 1.0001:
        return max(0.0, min(1.0, 1.0 - s))
    return max(0.0, min(1.0, 1.0 / (1.0 + max(0.0, s))))


def match_toxic_chroma(
    raw_sms: str,
    *,
    persist_directory: str,
    collection_name: str,
    embed_model: str | None = None,
    base_url: str | None = None,
) -> ToxicMatch:
    persist_directory = (persist_directory or "").strip()
    collection_name = (collection_name or "").strip()
    if not persist_directory or not collection_name:
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)

    m = embed_model if embed_model is not None else OLLAMA_MODEL
    u = base_url if base_url is not None else OLLAMA_BASE_URL
    emb = OllamaEmbeddings(model=m, base_url=u)
    try:
        store = Chroma(
            persist_directory=persist_directory,
            collection_name=collection_name,
            embedding_function=emb,
        )
        q = canonicalize_sms_for_toxic(raw_sms) or (raw_sms or "").strip()
        if not q:
            return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)
        pairs = store.similarity_search_with_score(q, k=1)
    except Exception as e:  # noqa: BLE001
        log.warning("Chroma 查詢失敗，略過 toxic_chroma err=%s", e)
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)

    if not pairs:
        return ToxicMatch(max_cosine=0.0, best_id=None, s_tox_0_100=0, embed_dim=0, toxic_count=0)

    doc, sc = pairs[0]
    sim = _score_to_cosine_similarity(float(sc))
    best_id: Optional[str] = None
    if doc.metadata and isinstance(doc.metadata.get("id"), str):
        best_id = doc.metadata["id"]
    elif doc.metadata and isinstance(doc.metadata.get("source"), str):
        best_id = doc.metadata["source"]
    stox = s_tox_from_max_cosine(sim)
    return ToxicMatch(
        max_cosine=float(sim),
        best_id=best_id,
        s_tox_0_100=int(stox),
        embed_dim=0,
        toxic_count=0,
    )
