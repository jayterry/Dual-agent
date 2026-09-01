"""共享特徵抽取：一次抽取、多路消費。"""

from __future__ import annotations

from dual_agent.dai.fraud_dual.shared.features.channel_features import extract_channel_features
from dual_agent.dai.fraud_dual.shared.features.intent_features import extract_intent_features
from dual_agent.dai.fraud_dual.shared.features.payload_features import extract_payload_features
from dual_agent.dai.fraud_dual.shared.features.rhetoric_features import extract_rhetoric_features
from dual_agent.dai.fraud_dual.shared.schemas import BuildGraphInput, SharedFeatures


def extract_shared(text: str, build_graph: BuildGraphInput) -> SharedFeatures:
    """從訊息本文 + 建圖欄位抽出 SharedFeatures。"""
    message = extract_rhetoric_features(text)
    intent = extract_intent_features(text)
    payload = extract_payload_features(text)
    channel = extract_channel_features(
        channel=build_graph.channel,
        primary_apps=list(build_graph.primary_apps),
    )
    return SharedFeatures(
        message_features=message,
        intent_features=intent,
        payload_features=payload,
        channel_features=channel,
        user_context={
            "age_band": build_graph.age_band,
            "occupation": build_graph.occupation,
            "relation_type": build_graph.relation_type,
            "invest_exp": build_graph.invest_exp,
        },
        text=text,
    )
