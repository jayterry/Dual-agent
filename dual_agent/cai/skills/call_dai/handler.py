from __future__ import annotations

import re
from typing import Any

from dual_agent.dai.invoke import invoke_dai
from dual_agent.dai.schemas import DAIRequest, DAIResult, DefenseObservation
from dual_agent.skill_types import SkillContext, SkillResult

ARGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "artifact": {
            "type": "string",
            "description": "待審全文（簡訊內容等）；優先於本輪輸入",
        },
        "user_text": {
            "type": "string",
            "description": "使用者說明（如「幫我看是否詐騙」）；可省略",
        },
        "context_pack": {"type": "string", "description": "可選長脈絡"},
        "sms_review": {
            "type": "boolean",
            "description": "預設 true：簡訊審查（Defense 先排 todos 再執行）",
        },
    },
    "required": [],
}


# 常見「還沒貼簡訊正文」的占位句；勿送進 DAI 以免誤判風險
_PLACEHOLDER_ARTIFACTS: frozenset[str] = frozenset(
    {
        "我收到一則簡訊",
        "我收到簡訊",
        "收到一則簡訊",
        "我剛收到簡訊",
        "我剛收到一則簡訊",
        "收到簡訊",
        "有一則簡訊",
        "我有一則簡訊",
        "剛收到一則簡訊",
        "收到一封簡訊",
        "我收到一封簡訊",
    }
)


def _norm_artifact(s: str) -> str:
    t = "".join(str(s).split())
    return t.strip("。．.!！？").strip()


def artifact_is_meta_only_intent(artifact: str) -> bool:
    """
    若為「僅宣告收到／要審簡訊」而無可審正文，回 True；Executor 應改走 ask_user，不呼叫 invoke_dai。
    """
    t = _norm_artifact(artifact)
    if not t:
        return True
    if len(t) > 48:
        return False
    low = t.lower()
    if "http://" in low or "https://" in low:
        return False
    if re.search(r"\d{4,}", t):
        return False
    if t in _PLACEHOLDER_ARTIFACTS:
        return True
    if len(t) <= 22:
        meta_patterns = (
            r"^幫我(看一下|看看)?(這)?則?簡訊$",
            r"^(請)?幫我審(一下)?(這)?則?簡訊$",
            r"^審(一下)?(這)?則?簡訊$",
            r"^幫我看是不是詐騙簡訊$",
        )
        for pat in meta_patterns:
            if re.match(pat, t):
                return True
    return False


def _boolish(v: Any, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("false", "0", "no", "off"):
        return False
    if s in ("true", "1", "yes", "on"):
        return True
    return default


def _observation_dict(o: DefenseObservation) -> dict[str, Any]:
    return {"skill": o.skill, "ok": o.ok, "summary": o.summary, "data": dict(o.data or {})}


def _evidence_reason_text(item: dict[str, Any]) -> str:
    note = str(item.get("note") or "").strip()
    if note:
        return note
    src = str(item.get("source") or "").strip()
    verdict = str(item.get("verdict") or "").strip()
    if src and verdict:
        return f"{src} 判定：{verdict}"
    if src:
        return f"證據來源：{src}"
    if verdict:
        return f"判定：{verdict}"
    if item:
        joined = "、".join(f"{k}={v}" for k, v in item.items())
        return joined.strip()
    return ""


def _reason_highlights(r: DAIResult, *, limit: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        s = str(text or "").strip()
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s[:160])

    for obs in r.defense_observations:
        add(obs.summary)
        if len(out) >= limit:
            return out

    for item in r.evidence:
        if isinstance(item, dict):
            add(_evidence_reason_text(item))
        elif isinstance(item, str):
            add(item)
        if len(out) >= limit:
            return out

    for label in r.risk_labels:
        add(f"風險標籤：{label}")
        if len(out) >= limit:
            return out
    return out


def _dai_payload(r: DAIResult) -> dict[str, Any]:
    return {
        "ok": r.ok,
        "risk_score": r.risk_score,
        "risk_labels": list(r.risk_labels),
        "safety_summary": r.safety_summary,
        "evidence": list(r.evidence),
        "tool_restrictions": dict(r.tool_restrictions or {}),
        "recommended_cai_action": r.recommended_cai_action,
        "defense_llm_turns": r.defense_llm_turns,
        "defense_observations": [_observation_dict(o) for o in r.defense_observations],
        "reason_highlights": _reason_highlights(r),
        "error": r.error,
    }


def handle(args: dict[str, Any], ctx: SkillContext) -> SkillResult:
    ctx_in = (ctx.user_input or "").strip()
    artifact = str(args.get("artifact") or "").strip()
    user_text = str(args.get("user_text") or "").strip()
    context_pack = str(args.get("context_pack") or "").strip()
    sms_review = _boolish(args.get("sms_review"), True)

    if not artifact:
        artifact = ctx_in
    if not user_text:
        user_text = ctx_in or "請審查下列內容"

    if not artifact.strip():
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary="缺少待審內容：請在 artifact 提供簡訊全文，或於對話中貼上內文",
            error="missing_artifact",
        )

    if artifact_is_meta_only_intent(artifact):
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary="尚未取得可審查的簡訊正文：請貼上完整簡訊內容（勿只送出「收到簡訊」等說明句）。",
            error="artifact_meta_only",
        )

    req = DAIRequest(
        user_text=user_text,
        artifact=artifact,
        context_pack=context_pack,
        sms_review=sms_review,
    )
    try:
        out = invoke_dai(req)
    except Exception as e:  # noqa: BLE001
        return SkillResult(
            ok=False,
            skill="call_dai",
            summary=f"DAI 呼叫失敗：{e}",
            error=str(e),
        )

    payload = _dai_payload(out)
    reasons = list(payload.get("reason_highlights") or [])
    head = (out.safety_summary or "").strip().split("\n", 1)[0][:400]
    score_head = f"風險分數 {out.risk_score}/100"
    if head:
        summary = f"[DAI] {score_head}；{head}"
    elif reasons:
        summary = f"[DAI] {score_head}；{reasons[0]}"
    else:
        summary = f"[DAI] {score_head}；建議動作 {out.recommended_cai_action}"
    return SkillResult(
        ok=out.ok,
        skill="call_dai",
        summary=summary,
        data={"dai": payload},
        evidence=[f"recommended_cai_action={out.recommended_cai_action}"],
    )
