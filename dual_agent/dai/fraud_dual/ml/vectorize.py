"""將 SharedFeatures 轉成 ML 數值向量（結構化部分）。"""

from __future__ import annotations

import numpy as np

from dual_agent.dai.fraud_dual.shared.constants import CHANNELS
from dual_agent.dai.fraud_dual.shared.schemas import SharedFeatures

STRUCTURED_FEATURE_NAMES: list[str] = [
    "urgency_score",
    "authority_score",
    "reward_score",
    "fear_score",
    "obfuscation_flag",
    "investment_keyword",
    "otp_keyword",
    "loan_keyword",
    "romance_keyword",
    "customer_service_keyword",
    "job_keyword",
    "log_money_amount",
    "contains_url",
    "url_is_shortener",
    "suspicious_tld",
    "contains_phone",
    "contains_account",
    "contains_apk",
    "apk_outside_store",
    "permission_request_count",
    "payload_risk_score",
    "channel_is_familiar",
    "channel_risk_score",
    *[f"channel_{c}" for c in CHANNELS],
]


def structured_vector(shared: SharedFeatures) -> np.ndarray:
    m = shared.message_features
    i = shared.intent_features
    p = shared.payload_features
    c = shared.channel_features
    channel_onehot = [1.0 if c.channel == name else 0.0 for name in CHANNELS]
    values = [
        m.urgency_score,
        m.authority_score,
        m.reward_score,
        m.fear_score,
        float(m.obfuscation_flag),
        float(i.investment_keyword),
        float(i.otp_keyword),
        float(i.loan_keyword),
        float(i.romance_keyword),
        float(i.customer_service_keyword),
        float(i.job_keyword),
        float(i.log_money_amount),
        float(p.contains_url),
        float(p.url_is_shortener),
        float(p.suspicious_tld),
        float(p.contains_phone),
        float(p.contains_account),
        float(p.contains_apk),
        float(p.apk_outside_store),
        float(p.permission_request_count),
        p.payload_risk_score,
        float(c.channel_is_familiar),
        c.channel_risk_score,
        *channel_onehot,
    ]
    return np.asarray(values, dtype=np.float64)
