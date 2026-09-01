"""Channel／熟悉度特徵。"""

from __future__ import annotations

from dual_agent.dai.fraud_dual.shared.keywords import CHANNEL_PRIOR_RISK
from dual_agent.dai.fraud_dual.shared.schemas import ChannelFeatures


def extract_channel_features(
    channel: str,
    primary_apps: list[str],
) -> ChannelFeatures:
    familiar = 1 if channel in primary_apps else 0
    return ChannelFeatures(
        channel=channel,  # type: ignore[arg-type]
        primary_apps=primary_apps,  # type: ignore[arg-type]
        channel_is_familiar=familiar,
        channel_risk_score=float(CHANNEL_PRIOR_RISK.get(channel, 0.4)),
    )
