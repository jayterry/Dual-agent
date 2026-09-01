"""Intent 關鍵字特徵。"""

from __future__ import annotations

from dual_agent.dai.fraud_dual.shared.features._textutil import count_keyword_hits, log_money_amount
from dual_agent.dai.fraud_dual.shared.keywords import INTENT_KEYWORDS
from dual_agent.dai.fraud_dual.shared.schemas import IntentFeatures


def extract_intent_features(text: str) -> IntentFeatures:
    return IntentFeatures(
        investment_keyword=count_keyword_hits(text, INTENT_KEYWORDS["investment_keyword"]),
        otp_keyword=count_keyword_hits(text, INTENT_KEYWORDS["otp_keyword"]),
        loan_keyword=count_keyword_hits(text, INTENT_KEYWORDS["loan_keyword"]),
        romance_keyword=count_keyword_hits(text, INTENT_KEYWORDS["romance_keyword"]),
        customer_service_keyword=count_keyword_hits(
            text, INTENT_KEYWORDS["customer_service_keyword"]
        ),
        job_keyword=count_keyword_hits(text, INTENT_KEYWORDS["job_keyword"]),
        log_money_amount=log_money_amount(text),
    )
