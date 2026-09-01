"""Pydantic 資料契約（對齊計劃書 §4、§6）。"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dual_agent.dai.fraud_dual.shared.constants import (
    AGE_BANDS,
    CHANNELS,
    OCCUPATIONS,
    RELATION_TYPES,
    SCAM_TYPES,
    AgeBand,
    ChannelType,
    Occupation,
    RelationType,
    ScamType,
)

Score01 = Annotated[float, Field(ge=0.0, le=1.0)]
Flag01 = Annotated[int, Field(ge=0, le=1)]


class BuildGraphInput(BaseModel):
    """建圖一次問完欄位（不含訊息本文）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    age_band: AgeBand
    occupation: Occupation
    relation_type: RelationType
    channel: ChannelType
    primary_apps: list[ChannelType] = Field(min_length=1)
    invest_exp: str | None = None

    @field_validator("age_band")
    @classmethod
    def _check_age(cls, v: str) -> str:
        if v not in AGE_BANDS:
            raise ValueError(f"age_band must be one of {AGE_BANDS}")
        return v

    @field_validator("occupation")
    @classmethod
    def _check_occupation(cls, v: str) -> str:
        if v not in OCCUPATIONS:
            raise ValueError(f"occupation must be one of {OCCUPATIONS}")
        return v

    @field_validator("relation_type")
    @classmethod
    def _check_relation(cls, v: str) -> str:
        if v not in RELATION_TYPES:
            raise ValueError(f"relation_type must be one of {RELATION_TYPES}")
        return v

    @field_validator("channel")
    @classmethod
    def _check_channel(cls, v: str) -> str:
        if v not in CHANNELS:
            raise ValueError(f"channel must be one of {CHANNELS}")
        return v

    @field_validator("primary_apps")
    @classmethod
    def _check_primary_apps(cls, apps: list[str]) -> list[str]:
        bad = [a for a in apps if a not in CHANNELS]
        if bad:
            raise ValueError(f"primary_apps invalid: {bad}; allowed={CHANNELS}")
        # 去重且保序
        seen: set[str] = set()
        out: list[str] = []
        for a in apps:
            if a not in seen:
                seen.add(a)
                out.append(a)
        return out


class AnalyzeRequest(BuildGraphInput):
    """POST /analyze 輸入：本文 + 建圖欄位。"""

    text: str = Field(min_length=1, description="訊息本文")
    include_path_b: bool = Field(
        default=True,
        description="是否呼叫 Path B（Ollama 純 LLM；不讀 Result_A）",
    )
    include_narrator: bool = Field(
        default=False,
        description="是否呼叫 Narrator（只解釋 Result_A）；尚未實作時略過",
    )


class MessageFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    urgency_score: Score01 = 0.0
    authority_score: Score01 = 0.0
    reward_score: Score01 = 0.0
    fear_score: Score01 = 0.0
    obfuscation_flag: Flag01 = 0


class IntentFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    investment_keyword: int = Field(ge=0, default=0)
    otp_keyword: int = Field(ge=0, default=0)
    loan_keyword: int = Field(ge=0, default=0)
    romance_keyword: int = Field(ge=0, default=0)
    customer_service_keyword: int = Field(ge=0, default=0)
    job_keyword: int = Field(ge=0, default=0)
    log_money_amount: float = Field(ge=0.0, default=0.0)


class PayloadFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contains_url: Flag01 = 0
    url_is_shortener: Flag01 = 0
    suspicious_tld: Flag01 = 0
    contains_phone: Flag01 = 0
    contains_account: Flag01 = 0
    contains_apk: Flag01 = 0
    apk_outside_store: Flag01 = 0
    permission_request_count: int = Field(ge=0, default=0)
    payload_risk_score: Score01 = 0.0


class ChannelFeatures(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: ChannelType
    primary_apps: list[ChannelType] = Field(min_length=1)
    channel_is_familiar: Flag01
    channel_risk_score: Score01 = 0.0


class SharedFeatures(BaseModel):
    """一次抽取、多路消費的特徵快照。"""

    model_config = ConfigDict(extra="forbid")

    message_features: MessageFeatures
    intent_features: IntentFeatures
    payload_features: PayloadFeatures
    channel_features: ChannelFeatures
    user_context: dict
    text: str


class ThreatResult(BaseModel):
    """Path A — ML Threat 輸出（尚不含 context_score）。"""

    model_config = ConfigDict(extra="forbid")

    threat_score: Score01
    threat_missing: Flag01 = 0
    scam_type: ScamType
    intent_confidence: Score01

    @field_validator("scam_type")
    @classmethod
    def _check_scam(cls, v: str) -> str:
        if v not in SCAM_TYPES:
            raise ValueError(f"scam_type must be one of {SCAM_TYPES}")
        return v


class GraphWriteback(BaseModel):
    """ML 回寫 Context Graph 的欄位（供 Phase 3 建圖）。"""

    model_config = ConfigDict(extra="forbid")

    message: dict
    intent: str
    payload_types: list[str] = Field(default_factory=list)


class ResultA(BaseModel):
    """Path A：ML Threat + GNN Context（分數禁止數值融合）。"""

    model_config = ConfigDict(extra="forbid")

    threat_score: Score01
    threat_missing: Flag01 = 0
    scam_type: ScamType
    intent_confidence: Score01
    context_score: Score01

    @field_validator("scam_type")
    @classmethod
    def _check_scam(cls, v: str) -> str:
        if v not in SCAM_TYPES:
            raise ValueError(f"scam_type must be one of {SCAM_TYPES}")
        return v

    @model_validator(mode="after")
    def _missing_threat_not_zero_safe(self) -> ResultA:
        if self.threat_missing == 1 and self.threat_score == 0.0:
            pass
        return self


class ResultB(BaseModel):
    """Path B：純 LLM（不得讀取 Result_A 分數）。"""

    model_config = ConfigDict(extra="forbid")

    llm_threat: Score01
    llm_scam_type: ScamType
    llm_context: Score01
    llm_channel_familiar: bool
    explanation: str

    @field_validator("llm_scam_type")
    @classmethod
    def _check_scam(cls, v: str) -> str:
        if v not in SCAM_TYPES:
            raise ValueError(f"llm_scam_type must be one of {SCAM_TYPES}")
        return v


class AnalyzeResponse(BaseModel):
    """雙路並列輸出。"""

    model_config = ConfigDict(extra="forbid")

    shared_features: SharedFeatures | None = None
    threat: ThreatResult | None = None
    graph_writeback: GraphWriteback | None = None
    result_a: ResultA | None = None
    result_b: ResultB | None = None
    narrator_text: str | None = None
    phase: str = Field(
        default="0",
        description="實作階段標示",
    )
    status: str = Field(
        default="scaffold",
        description="scaffold | ok | partial | error",
    )
    detail: str | None = None
