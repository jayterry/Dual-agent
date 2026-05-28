"""截圖回報：Memory format、待審晉升、Replan 訊息隱藏。"""

from dual_agent.cai.plan_execute import (
    _pending_review_should_promote_raw_input,
    _user_visible_answer,
)
from dual_agent.ingress import normalize_ingress


def test_user_visible_answer_hides_replan_internal() -> None:
    raw = "（已停止：待辦已空但 Replan 未標記完成。）"
    out = _user_visible_answer(raw)
    assert "Replan" not in out
    assert "待辦已空" not in out
    assert "請再試一次" in out


def test_pending_review_promotes_threat_relay() -> None:
    ing = normalize_ingress(raw_input_text="他說要殺了我", input_origin="chat_box")
    assert _pending_review_should_promote_raw_input(ing)


def test_threat_relay_not_meta_only_ingress() -> None:
    ing = normalize_ingress(raw_input_text="他說要殺了我", input_origin="chat_box")
    assert ing.requires_dai is True
    assert (ing.artifact_text or "").strip() == "他說要殺了我"
