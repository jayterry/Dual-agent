"""共享層：封閉集常數、資料契約、特徵抽取。"""

from dual_agent.dai.fraud_dual.shared.constants import (
    AGE_BANDS,
    CHANNELS,
    OCCUPATIONS,
    PAYLOAD_TYPES,
    RELATION_TYPES,
    SCAM_TYPES,
)
from dual_agent.dai.fraud_dual.shared.features import extract_shared
from dual_agent.dai.fraud_dual.shared.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    BuildGraphInput,
    ChannelFeatures,
    GraphWriteback,
    IntentFeatures,
    MessageFeatures,
    PayloadFeatures,
    ResultA,
    ResultB,
    SharedFeatures,
    ThreatResult,
)

__all__ = [
    "AGE_BANDS",
    "CHANNELS",
    "OCCUPATIONS",
    "PAYLOAD_TYPES",
    "RELATION_TYPES",
    "SCAM_TYPES",
    "AnalyzeRequest",
    "AnalyzeResponse",
    "BuildGraphInput",
    "ChannelFeatures",
    "GraphWriteback",
    "IntentFeatures",
    "MessageFeatures",
    "PayloadFeatures",
    "ResultA",
    "ResultB",
    "SharedFeatures",
    "ThreatResult",
    "extract_shared",
]
