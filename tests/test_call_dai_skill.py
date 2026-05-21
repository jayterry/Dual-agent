"""CAI skill call_dai：mock invoke_dai，不依賴 Ollama。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dual_agent.cai.executor import format_results_for_display
from dual_agent.dai.schemas import DAIResult, DefenseObservation
from dual_agent.skill_types import SkillContext
from dual_agent.skills_registry import SKILLS, run_skill


def _call_dai_handle():
    return SKILLS["call_dai"].handler


def test_call_dai_skill_mock() -> None:
    fake = DAIResult(
        ok=True,
        risk_score=42,
        risk_labels=["test"],
        safety_summary="摘要：測試通過",
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="continue",
        defense_observations=[
            DefenseObservation(skill="guard_scan", ok=True, summary="scan ok", data={"verdict": "review"})
        ],
        defense_llm_turns=1,
        error=None,
    )
    m = MagicMock(return_value=fake)
    # importlib 載入的 handler 不在 sys.modules，無法用字串路徑 patch
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill(
            "call_dai",
            {"artifact": "【測試】內文", "user_text": "幫我看", "sms_review": True},
            SkillContext(user_input="幫我看"),
        )
    m.assert_called_once()
    assert r.ok
    assert r.skill == "call_dai"
    assert "DAI" in r.summary
    assert "風險分數" in r.summary
    dai = r.data.get("dai") or {}
    assert dai.get("risk_score") == 42
    assert dai.get("reason_highlights") == []


def test_call_dai_skill_missing_body() -> None:
    m = MagicMock()
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill("call_dai", {"artifact": ""}, SkillContext(user_input=""))
    m.assert_not_called()
    assert not r.ok
    assert r.error == "missing_artifact"


def test_call_dai_rejects_meta_placeholder_artifact() -> None:
    m = MagicMock()
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill(
            "call_dai",
            {"artifact": "我收到一則簡訊"},
            SkillContext(user_input="我收到一則簡訊"),
        )
    m.assert_not_called()
    assert not r.ok
    assert r.error == "artifact_meta_only"


def test_call_dai_accepts_substantive_sms_body() -> None:
    fake = DAIResult(
        ok=True,
        risk_score=90,
        risk_labels=[],
        safety_summary="高風險",
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="block",
        defense_observations=[],
        defense_llm_turns=1,
        error=None,
    )
    m = MagicMock(return_value=fake)
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill(
            "call_dai",
            {"artifact": "你的小孩在我手上，支付贖金300萬給我"},
            SkillContext(user_input="你的小孩在我手上，支付贖金300萬給我"),
        )
    m.assert_called_once()
    assert r.ok


def test_call_dai_display_excerpt_includes_display_text() -> None:
    display = (
        "風險分數：88/100\n判定：block\n\n主要原因：\n• 涉及匯款\n\n建議：\n• 不要匯款"
    )
    full_report = {
        "risk_score": 88,
        "verdict": "block",
        "recommended_cai_action": "block",
        "safety_summary": "綜合風險 88/100，判定 block。",
        "component_scores": {"r_rules": 40},
        "display_text": display,
        "user_reason_highlights": ["涉及匯款"],
        "user_suggestions": ["不要匯款"],
        "reason_highlights": ["硬規則命中（40 分）"],
        "labels": [],
        "track_a": {},
        "analysis_payload": {},
    }
    fake = DAIResult(
        ok=True,
        risk_score=88,
        risk_labels=["scam"],
        safety_summary=full_report["safety_summary"],
        evidence=[],
        tool_restrictions={},
        recommended_cai_action="block",
        defense_observations=[
            DefenseObservation(
                skill="fuse_risk_and_ueba",
                ok=True,
                summary="fuse ok",
                data={"step": "fuse_risk_and_ueba", "report": full_report},
            ),
        ],
        defense_llm_turns=1,
        error=None,
    )
    m = MagicMock(return_value=fake)
    with patch.dict(_call_dai_handle().__globals__, {"invoke_dai": m}):
        r = run_skill(
            "call_dai",
            {"artifact": "付款給我，不然對你不利"},
            SkillContext(user_input="付款給我，不然對你不利"),
        )
    shown = format_results_for_display([r])
    assert "風險分數：88/100" in shown
    assert "判定：block" in shown
    assert "主要原因：" in shown
