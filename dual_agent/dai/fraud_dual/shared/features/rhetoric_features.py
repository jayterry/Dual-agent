"""Message 話術特徵。"""

from __future__ import annotations

import re

from dual_agent.dai.fraud_dual.shared.features._textutil import count_keyword_hits, score_from_hits
from dual_agent.dai.fraud_dual.shared.keywords import OBFUSCATION_PATTERNS, RHETORIC
from dual_agent.dai.fraud_dual.shared.schemas import MessageFeatures


def extract_rhetoric_features(text: str) -> MessageFeatures:
    urgency_hits = count_keyword_hits(text, RHETORIC["urgency"])
    authority_hits = count_keyword_hits(text, RHETORIC["authority"])
    reward_hits = count_keyword_hits(text, RHETORIC["reward"])
    fear_hits = count_keyword_hits(text, RHETORIC["fear"])

    obfuscation = 0
    for pat in OBFUSCATION_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            obfuscation = 1
            break

    return MessageFeatures(
        urgency_score=score_from_hits(urgency_hits),
        authority_score=score_from_hits(authority_hits),
        reward_score=score_from_hits(reward_hits),
        fear_score=score_from_hits(fear_hits),
        obfuscation_flag=obfuscation,
    )
