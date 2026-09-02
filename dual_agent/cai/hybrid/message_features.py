"""MessageFeatures NLP：Ollama JSON 特徵抽取。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_ollama import ChatOllama

from dual_agent.cai.hybrid.prompts import load_fewshots, load_prompt
from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.cai.pipeline_progress import advance_pipeline_node
from dual_agent.config import OLLAMA_BASE_URL, cai_message_features_model
from dual_agent.llm_json import invoke_and_parse_json
from dual_agent.skill_types import SkillContext


def _merge_l0_artifact(
    features: MessageFeatures,
    *,
    artifact_from_api: str | None,
    body_source: str | None,
) -> MessageFeatures:
    art = (artifact_from_api or "").strip()
    if art:
        features.content.artifact_text = art
        features.content.has_reviewable_body = True
        if body_source in ("inline", "api_split", "sms_share"):
            features.content.body_source = body_source  # type: ignore[assignment]
        if features.turn_intent.primary_goal == "ask_missing_body":
            features.turn_intent.primary_goal = "review_sms"
            features.gaps.missing_body_for_review = False
            features.capabilities.domain_tags = ["safety_review"]
            features.capabilities.suggested_skills = ["call_dai"]
    return features


def _fallback_features(user_text: str) -> MessageFeatures:
    t = (user_text or "").strip()
    from dual_agent.cai.hybrid.schemas import CapabilityFeatures, ContentFeatures, GapFeatures, TurnIntent

    return MessageFeatures(
        turn_intent=TurnIntent(
            primary_goal="out_of_scope",
            confidence=0.3,
            intent_rationale_zh="NLP 解析失敗，保守標記為超出範圍。",
        ),
        content=ContentFeatures(user_comment=t, text_length=len(t)),
        gaps=GapFeatures(out_of_product_scope=True),
        capabilities=CapabilityFeatures(
            required_types=["direct_response"],
            domain_tags=["out_of_scope"],
        ),
    )


def _format_fewshots(max_examples: int = 3) -> str:
    data = load_fewshots("message_features.json")
    examples = data.get("examples") or []
    picked = examples[:max_examples]
    return json.dumps(picked, ensure_ascii=False, indent=2)


def _build_user_message(
    *,
    user_text: str,
    context_pack: str | None,
    input_origin: str,
    artifact_from_api: str | None,
    task_snapshot: dict | None,
    pending_review: bool,
    pending_memory_confirm: bool,
) -> str:
    parts = [
        "【本輪使用者輸入】",
        user_text or "",
        "",
        "【通道信號】",
        f"input_origin={input_origin}",
        f"artifact_from_api={artifact_from_api or ''}",
        "",
        "【Context Pack】",
        (context_pack or "").strip() or "（無）",
        "",
        "【上一輪任務狀態 JSON】",
        json.dumps(task_snapshot or {}, ensure_ascii=False),
        "",
        "【待確認旗標】",
        f"pending_review={pending_review}",
        f"pending_memory_confirm={pending_memory_confirm}",
        "",
        "【Few-shot 參考】",
        _format_fewshots(),
    ]
    return "\n".join(parts)


def invoke_message_features(
    *,
    user_text: str,
    context_pack: str | None = None,
    input_origin: str = "chat_box",
    artifact_from_api: str | None = None,
    body_source: str | None = None,
    pending_review: bool = False,
    pending_memory_confirm: bool = False,
    task_snapshot: dict | None = None,
    model: str | None = None,
    base_url: str = OLLAMA_BASE_URL,
    temperature: float = 0.1,
    pipeline_ctx: SkillContext | None = None,
) -> MessageFeatures:
    if pipeline_ctx is not None:
        advance_pipeline_node(pipeline_ctx, "message_features", model=model or cai_message_features_model())
    llm = ChatOllama(
        model=model or cai_message_features_model(),
        base_url=base_url,
        temperature=temperature,
    )
    system = load_prompt("nlp_system")
    user_msg = _build_user_message(
        user_text=user_text,
        context_pack=context_pack,
        input_origin=input_origin,
        artifact_from_api=artifact_from_api,
        task_snapshot=task_snapshot,
        pending_review=pending_review,
        pending_memory_confirm=pending_memory_confirm,
    )
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", "{user}")])
    chain = prompt | llm | StrOutputParser()

    def _invoke() -> dict[str, Any]:
        raw = chain.invoke({"user": user_msg})
        return json.loads(raw) if isinstance(raw, str) else raw

    try:
        obj = invoke_and_parse_json(_invoke)
        features = MessageFeatures.model_validate(obj)
    except Exception:  # noqa: BLE001
        features = _fallback_features(user_text)
    features = _merge_l0_artifact(
        features,
        artifact_from_api=artifact_from_api,
        body_source=body_source,
    )
    if pipeline_ctx is not None:
        pipeline_ctx.policy_state["message_features"] = features.model_dump()
    return features
