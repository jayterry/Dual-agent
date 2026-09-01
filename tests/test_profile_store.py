"""profile_store 與 known_relations 推斷。"""

from __future__ import annotations

from pathlib import Path

from dual_agent.cai.profile_store import (
    get_profile,
    looks_like_money_not_name,
    match_known_name_in_text,
    sync_relations_from_user_facts,
    to_dai_persona,
    upsert_fields,
    upsert_relation,
)


def test_upsert_and_to_dai_persona(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    upsert_fields(
        {
            "age_band": "40-59",
            "occupation": "office",
            "primary_apps": "LINE,SMS",
            "invest_exp": "新手",
        },
        db_path=db,
    )
    p = to_dai_persona(db_path=db)
    assert p["age_band"] == "40-59"
    assert p["occupation"] == "office"
    assert "LINE" in p["primary_apps"]
    assert p["invest_exp"] == "新手"
    assert "channel" not in p
    assert "relation_type" not in p


def test_money_not_name() -> None:
    assert looks_like_money_not_name("300萬")
    assert looks_like_money_not_name("1000元")
    assert not looks_like_money_not_name("小明")


def test_known_name_hit_family(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    upsert_relation("兒子", "小明", db_path=db)
    hit = match_known_name_in_text(
        "小明跟我說要匯款去投資",
        db_path=db,
    )
    assert hit is not None
    assert hit["relation_type"] == "Family"
    assert hit["matched_name"] == "小明"


def test_sync_from_user_facts(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    sync_relations_from_user_facts(
        {"relations": {"媽媽": ["阿美"], "同事": ["Jay"]}},
        db_path=db,
    )
    hit = match_known_name_in_text("阿美傳訊息給我", db_path=db)
    assert hit and hit["relation_type"] == "Family"
