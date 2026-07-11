"""特徵規格 v1：與 model.pkl 綁定的固定特徵名稱順序。"""

from __future__ import annotations

FEATURE_SPEC_VERSION = "risk_features_v1"

RULE_IDS: tuple[str, ...] = (
    "password_credentials",
    "otp",
    "card_bank_sensitive",
    "national_id_ubn",
    "local_payment_pin",
    "payment_ransom_threat",
    "physical_threat",
    "high_risk_combo_link_account_urgent",
    "loan_scam",
    "nh_card_loan",
    "unsolicited_loan_pitch",
    "identity_scam_framework",
    "low_finance_notify",
)

CONTINUOUS_SCORE_KEYS: tuple[str, ...] = (
    "r_rules",
    "r_threat_intel",
    "r_tls",
    "r_toxic_fused",
    "tier_h",
    "tier_i",
    "r_llm_optional",
)

MACHINE_DERIVED_KEYS: tuple[str, ...] = (
    "r_machine_base",
    "r_machine_support_bonus",
    "r_machine_final",
    "r_llm_100",
)

SEMANTIC_LABEL_KEYS: tuple[str, ...] = (
    "financial_extortion",
    "payment_pressure",
    "physical_threat",
    "credential_harvesting",
    "phishing",
    "impersonation",
    "malicious_link",
    "urgency_pressure",
    "suspicious_notification",
)

STRUCTURE_KEYS: tuple[str, ...] = (
    "text_len",
    "url_count",
    "has_https",
    "phone_count",
    "amount_count",
    "toxic_max_cosine",
    "ti_vendor_count_max",
    "missing_evidence_count",
)

UEBA_KEYS: tuple[str, ...] = (
    "delta_user",
    "s_user",
    "source_trusted",
    "source_blocked",
    "domain_unknown",
)

SOURCE_CHANNEL_KEYS: tuple[str, ...] = (
    "src_sms",
    "src_notification",
    "src_desktop",
    "src_unknown",
)


def _prefixed(prefix: str, keys: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{prefix}{k}" for k in keys)


def all_feature_names() -> tuple[str, ...]:
    return (
        _prefixed("hit_", RULE_IDS)
        + CONTINUOUS_SCORE_KEYS
        + MACHINE_DERIVED_KEYS
        + _prefixed("lbl_", SEMANTIC_LABEL_KEYS)
        + STRUCTURE_KEYS
        + UEBA_KEYS
        + SOURCE_CHANNEL_KEYS
    )
