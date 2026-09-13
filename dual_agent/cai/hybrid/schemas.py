"""MessageFeatures 與 ReAct 輸出 schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PrimaryGoal = Literal[
    "review_sms",
    "ask_missing_body",
    "follow_up_review",
    "remember_relation",
    "recall_relation",
    "assistant_chat",
    "out_of_scope",
]

BodySource = Literal["inline", "api_split", "sms_share"]

TurnRelation = Literal[
    "continue",
    "clarify",
    "correct",
    "aside",
    "switch",
    "cancel",
]

WorkScope = Literal["in_scope", "out_of_scope"]


class TurnIntent(BaseModel):
    primary_goal: PrimaryGoal = "out_of_scope"
    is_follow_up: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    intent_rationale_zh: str = ""
    # 增量：本輪與現行工作的關係／細意圖／範圍（不取代 primary_goal）
    turn_relation: TurnRelation | None = None
    intent: str | None = None
    scope: WorkScope | None = None
    provided_fields: dict[str, Any] = Field(default_factory=dict)
    needs_clarification: bool = False


class ContentFeatures(BaseModel):
    has_reviewable_body: bool = False
    artifact_text: str | None = None
    user_comment: str | None = None
    body_source: BodySource = "inline"
    contains_url: bool = False
    contains_phone: bool = False
    contains_financial_terms: bool = False
    scam_signal_tags: list[str] = Field(default_factory=list)
    text_length: int = 0


class SocialFeatures(BaseModel):
    mentions_relation: bool = False
    relation_category: str | None = None
    relation_label: str | None = None
    relation_name: str | None = None
    on_behalf_of_other: bool = False


class GapFeatures(BaseModel):
    missing_body_for_review: bool = False
    needs_profile_relation_confirm: bool = False
    out_of_product_scope: bool = False


class CapabilityFeatures(BaseModel):
    required_types: list[str] = Field(default_factory=list)
    domain_tags: list[str] = Field(default_factory=list)
    suggested_skills: list[str] = Field(default_factory=list)
    is_multi_step: bool = False


class MessageFeatures(BaseModel):
    turn_intent: TurnIntent = Field(default_factory=TurnIntent)
    content: ContentFeatures = Field(default_factory=ContentFeatures)
    social: SocialFeatures = Field(default_factory=SocialFeatures)
    gaps: GapFeatures = Field(default_factory=GapFeatures)
    capabilities: CapabilityFeatures = Field(default_factory=CapabilityFeatures)

    @property
    def primary_goal(self) -> str:
        return self.turn_intent.primary_goal

    @property
    def turn_relation(self) -> str | None:
        return self.turn_intent.turn_relation

    def model_dump_json_compact(self) -> str:
        return self.model_dump_json(exclude_none=True)


class ReActAction(BaseModel):
    type: Literal["tool", "ask_user", "finish", "decline"]
    skill: str | None = None
    args: dict | None = None
    question: str | None = None
    final_answer: str | None = None


class ReActOutput(BaseModel):
    thought: str = ""
    action: ReActAction
