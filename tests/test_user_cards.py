"""使用者面向雙卡：線索、情境因素、純文字備援。"""

from __future__ import annotations

from dual_agent.dai.fraud_dual.shared.features import extract_shared
from dual_agent.dai.fraud_dual.shared.schemas import BuildGraphInput, ResultA
from dual_agent.dai.risk_analysis.user_cards import (
    LIMITATION_PROTOTYPE,
    build_context_factor_labels,
    build_headline,
    build_limitations,
    build_threat_clues,
    context_card_title,
    format_user_display,
    is_hetero_backend,
)


def test_threat_clues_short_url_apk_urgency() -> None:
    text = "限時30分鐘下載 App https://bit.ly/abc 否則帳戶停用"
    clues = build_threat_clues(text)
    assert "限時要求" in clues
    assert "短網址" in clues
    assert "下載 App" in clues


def test_context_factors_unfamiliar_telegram() -> None:
    build = BuildGraphInput(
        age_band="25-39",
        occupation="office",
        relation_type="Unknown",
        channel="Telegram",
        primary_apps=["SMS", "LINE"],
        invest_exp=None,
    )
    shared = extract_shared("客服請立刻點連結驗證 https://bit.ly/x", build)
    ra = ResultA(
        threat_score=0.8,
        scam_type="Fake_CS",
        intent_confidence=0.7,
        context_score=0.6,
        context_backend="hetero_sage_ranking_v1",
    )
    labels = build_context_factor_labels(
        shared=shared,
        persona={
            "channel": "Telegram",
            "primary_apps": ["SMS", "LINE"],
            "relation_type": "Unknown",
            "age_band": "25-39",
            "occupation": "office",
        },
        result_a=ra,
    )
    assert any("Telegram" in x and "非常用" in x for x in labels)
    assert any("Unknown" in x or "人設不一致" in x for x in labels)


def test_headline_and_limitations() -> None:
    assert build_headline("block", 90) == "建議先不要點擊或安裝"
    assert build_headline("warn", 72) == "先查證再操作"
    assert build_headline("allow", 20) == ""
    lim = build_limitations(relation="Unknown")
    assert lim == [LIMITATION_PROTOTYPE]
    assert "僅供參考" in lim[0]
    assert "非法律意見" in lim[0] or "官方判定" in lim[0]
    assert "受害機率" in lim[0]
    assert "165" in lim[0]
    assert not any("原型" in x for x in lim)
    assert not any("Unknown" in x for x in lim)


def test_format_user_display_hides_path_b() -> None:
    text = format_user_display(
        headline="建議先不要點擊或安裝",
        instruction="請自行開啟官方 App 查證；必要時聯絡 165。",
        threat_score_100=88,
        context_score_100=41,
        threat_clues=["限時要求", "短網址"],
        context_factors=["Telegram 非常用平台"],
        context_backend="hetero_sage_ranking_v1",
        limitations=[LIMITATION_PROTOTYPE],
        narrator="這則聽起來很催，自己開官方 App 查就好。",
        suggestions=["請自行開啟官方 App 查證；必要時聯絡 165。"],
    )
    assert "Path A" not in text
    assert "Path B" not in text
    assert "Threat" not in text
    assert "ML / LLM 訊息線索" in text
    assert "GNN 情境因素" in text
    assert "僅供參考" in text
    assert "受害機率" in text
    assert "88/100" in text
    assert is_hetero_backend("hetero_sage_ranking_v1")
    assert context_card_title("learned_v1") == "情境因素"
