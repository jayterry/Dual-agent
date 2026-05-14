"""desktop_cai_app：UI 層固定顯示 DAI 風險摘要。"""

from __future__ import annotations

from desktop_cai_app import (
    _build_dai_result_block,
    _build_memory_assistant_text,
    _build_plan_block,
    _extract_latest_call_dai_payload,
)
from dual_agent.cai.schemas import PlanStep
from dual_agent.skill_types import SkillResult


def test_extract_latest_call_dai_payload_returns_latest() -> None:
    results = [
        SkillResult(ok=True, skill="weather", summary="ok"),
        SkillResult(ok=True, skill="call_dai", summary="old", data={"dai": {"risk_score": 10}}),
        SkillResult(ok=True, skill="call_dai", summary="new", data={"dai": {"risk_score": 88}}),
    ]
    payload = _extract_latest_call_dai_payload(results)
    assert isinstance(payload, dict)
    assert payload.get("risk_score") == 88


def test_build_dai_result_block_includes_score_action_summary_and_reasons() -> None:
    results = [
        SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 88/100",
            data={
                "dai": {
                    "risk_score": 88,
                    "recommended_cai_action": "block",
                    "safety_summary": "高風險詐騙，請勿匯款。",
                    "reason_highlights": [
                        "要求支付大額金錢",
                        "帶有威脅與施壓語氣",
                    ],
                }
            },
        )
    ]
    shown = _build_dai_result_block(results)
    assert "【DAI 風險摘要】" in shown
    assert "風險分數：88/100" in shown
    assert "建議動作：block" in shown
    assert "摘要：高風險詐騙，請勿匯款。" in shown
    assert "主要原因：" in shown
    assert "- 要求支付大額金錢" in shown


def test_build_dai_result_block_empty_when_no_call_dai() -> None:
    results = [SkillResult(ok=True, skill="weather", summary="ok")]
    assert _build_dai_result_block(results) == ""


def test_build_plan_block_redacts_call_dai_context_pack() -> None:
    plan = [
        PlanStep(
            skill="call_dai",
            args={
                "artifact": "你男友在我手上，給我500萬",
                "user_text": "請審查這則威脅訊息",
                "context_pack": "【最近對話緩衝】很多很多內容",
                "sms_review": True,
            },
        )
    ]
    shown = _build_plan_block(plan)
    assert "計畫步驟數：1" in shown
    assert "請審查這則威脅訊息" in shown
    assert "（已省略）" in shown
    assert "很多很多內容" not in shown


def test_build_memory_assistant_text_excludes_plan_block_and_keeps_dai_summary() -> None:
    results = [
        SkillResult(
            ok=True,
            skill="call_dai",
            summary="[DAI] 風險分數 91/100",
            data={"dai": {"risk_score": 91, "reason_highlights": ["勒索"]}},
        )
    ]
    shown = _build_memory_assistant_text("請立即報警。", results)
    assert shown.startswith("請立即報警。")
    assert "【DAI 風險摘要】" in shown
    assert "計畫步驟數" not in shown
