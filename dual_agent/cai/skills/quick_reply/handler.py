from __future__ import annotations

from typing import Any

from dual_agent.cai.hybrid.schemas import MessageFeatures
from dual_agent.skill_types import SkillContext, SkillResult

KIND_GREET = "greet"
KIND_THANKS = "thanks"
KIND_CAPABILITY = "capability"
KIND_IDENTITY_USER = "identity_user"
KIND_IDENTITY_ASSISTANT = "identity_assistant"
KIND_OUT_OF_SCOPE = "out_of_scope"

KINDS: frozenset[str] = frozenset(
    {
        KIND_GREET,
        KIND_THANKS,
        KIND_CAPABILITY,
        KIND_IDENTITY_USER,
        KIND_IDENTITY_ASSISTANT,
        KIND_OUT_OF_SCOPE,
    }
)

# 同時出現多個 tag 時：身份 > 能力 > 道謝 > 問候 > 超出範圍
_KIND_PRIORITY: tuple[str, ...] = (
    KIND_IDENTITY_USER,
    KIND_IDENTITY_ASSISTANT,
    KIND_CAPABILITY,
    KIND_THANKS,
    KIND_GREET,
    KIND_OUT_OF_SCOPE,
)

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": sorted(KINDS),
            "description": "回覆種類；缺省由 MessageFeatures 推斷",
        }
    },
    "required": [],
}


def display_name_from_ctx(ctx: SkillContext) -> str:
    ps = ctx.policy_state if isinstance(ctx.policy_state, dict) else {}
    prof = ps.get("user_profile")
    if isinstance(prof, dict):
        name = str(prof.get("display_name") or prof.get("displayName") or "").strip()
        if name:
            return name
    uf = ps.get("user_facts")
    if isinstance(uf, dict):
        nested = uf.get("profile")
        if isinstance(nested, dict):
            name = str(nested.get("display_name") or nested.get("name") or "").strip()
            if name:
                return name
    pack = str(ps.get("context_pack") or "").strip()
    if pack:
        from dual_agent.cai.context_layer import extract_user_display_name_from_pack

        found = extract_user_display_name_from_pack(pack)
        if found:
            return found
    return ""


def _features_from_ctx(ctx: SkillContext) -> MessageFeatures | None:
    raw = ctx.policy_state.get("message_features")
    if not isinstance(raw, dict):
        return None
    try:
        return MessageFeatures.model_validate(raw)
    except Exception:  # noqa: BLE001
        return None


def resolve_kind(args: dict[str, Any] | None, features: MessageFeatures | None) -> str:
    raw = str((args or {}).get("kind") or "").strip().lower()
    if raw in KINDS:
        return raw
    tags = [str(t).strip().lower() for t in (features.capabilities.domain_tags if features else [])]
    for kind in _KIND_PRIORITY:
        if kind in tags:
            return kind
    if features is not None and features.primary_goal == "out_of_scope":
        return KIND_OUT_OF_SCOPE
    if features is not None and features.primary_goal == "assistant_chat":
        return KIND_GREET
    return KIND_OUT_OF_SCOPE


def render_reply(kind: str, *, display_name: str = "") -> str:
    name = (display_name or "").strip()
    if kind == KIND_GREET:
        if name:
            return f"您好，{name}。我是防詐助理，可以把可疑簡訊貼過來給我看。"
        return (
            "您好，我是防詐助理，可以把可疑簡訊貼過來給我看。"
            "若希望我用名字稱呼您，可在個人資料填寫稱呼。"
        )
    if kind == KIND_IDENTITY_ASSISTANT:
        return "我是防詐助理，專門幫您檢視訊息風險，不是通用聊天機器人。"
    if kind == KIND_IDENTITY_USER:
        if name:
            return f"您是 {name}。"
        return "我這邊還沒記住您的稱呼，可在個人資料填名稱，或直接告訴我怎麼稱呼您。"
    if kind == KIND_THANKS:
        return "不客氣。之後若收到奇怪簡訊，把全文貼上來即可。"
    if kind == KIND_CAPABILITY:
        return (
            "我可以幫您審查簡訊或可疑訊息是不是詐騙、缺正文時再請您補上，"
            "也可以記住或回想親友稱呼。"
            "天氣、搜網、寫程式、陪聊這些我還沒提供。"
        )
    return "這項我還沒提供。我目前只做訊息防詐——把完整簡訊貼上來，我可以幫您看風險。"


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    features = _features_from_ctx(ctx)
    kind = resolve_kind(args, features)
    name = display_name_from_ctx(ctx)
    text = render_reply(kind, display_name=name)
    return SkillResult(
        ok=True,
        skill="quick_reply",
        summary=text,
        data={"kind": kind, "display_name": name or None},
    )
