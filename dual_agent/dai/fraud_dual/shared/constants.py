"""封閉集合（對齊計劃書 §16）。"""

from __future__ import annotations

from typing import Final, Literal

# --- Literals（供型別檢查與 IDE）---

ScamType = Literal[
    "Investment",
    "Loan",
    "Romance",
    "Fake_CS",
    "OTP_Scam",
    "Job_Scam",
    "Gov_Subsidy",
    "Impersonation_Authority",
    "Parcel",
    "Account_Freeze",
    "Unknown",
]

ChannelType = Literal[
    "LINE",
    "Telegram",
    "SMS",
    "Email",
    "Facebook",
    "Website",
]

RelationType = Literal[
    "Family",
    "Friend",
    "Colleague",
    "Official",
    "Unknown",
]

PayloadType = Literal[
    "URL",
    "APP",
    "Account",
    "Phone",
    "Permission",
]

AgeBand = Literal["<25", "25-39", "40-59", "60+"]

Occupation = Literal[
    "student",
    "office",
    "freelance",
    "retired",
    "other",
]

# --- 執行期常數（校驗用）---

SCAM_TYPES: Final[tuple[ScamType, ...]] = (
    "Investment",
    "Loan",
    "Romance",
    "Fake_CS",
    "OTP_Scam",
    "Job_Scam",
    "Gov_Subsidy",
    "Impersonation_Authority",
    "Parcel",
    "Account_Freeze",
    "Unknown",
)

CHANNELS: Final[tuple[ChannelType, ...]] = (
    "LINE",
    "Telegram",
    "SMS",
    "Email",
    "Facebook",
    "Website",
)

RELATION_TYPES: Final[tuple[RelationType, ...]] = (
    "Family",
    "Friend",
    "Colleague",
    "Official",
    "Unknown",
)

PAYLOAD_TYPES: Final[tuple[PayloadType, ...]] = (
    "URL",
    "APP",
    "Account",
    "Phone",
    "Permission",
)

AGE_BANDS: Final[tuple[AgeBand, ...]] = (
    "<25",
    "25-39",
    "40-59",
    "60+",
)

OCCUPATIONS: Final[tuple[Occupation, ...]] = (
    "student",
    "office",
    "freelance",
    "retired",
    "other",
)

# Channel 必填、v1 無 Unknown；Relation / Intent 可 Unknown
CHANNEL_ALLOWS_UNKNOWN: Final[bool] = False
RELATION_ALLOWS_UNKNOWN: Final[bool] = True
