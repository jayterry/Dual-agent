"""Pipeline 階段與流程圖節點（手機輪詢）。"""

from dual_agent.cai.pipeline_progress import (
    advance_pipeline_node,
    build_step_list,
    get_pipeline_status,
    init_pipeline_run,
    set_pipeline_stage,
    splice_dai_nodes,
)
from dual_agent.skill_types import SkillContext


def test_build_step_list_execute_is_active_index_3() -> None:
    steps = build_step_list("chat", "execute")
    assert len(steps) == 5
    assert steps[3]["id"] == "execute"
    assert steps[3]["status"] == "active"
    assert steps[0]["status"] == "done"
    assert steps[4]["status"] == "pending"


def test_get_pipeline_status_empty() -> None:
    ctx = SkillContext(user_input="")
    st = get_pipeline_status(ctx)
    assert st["label_zh"] == "準備中…"
    assert st["current_index"] == -1
    assert st["nodes"] == []


def test_set_pipeline_detail() -> None:
    ctx = SkillContext(user_input="")
    init_pipeline_run(ctx, "chat")
    set_pipeline_stage(ctx, flow="chat", stage="execute", detail="call_dai")
    st = get_pipeline_status(ctx)
    assert st["flow"] == "chat"
    assert st["stage"] == "execute"
    assert st["detail_label_zh"] == "風險分析"
    ids = [n["id"] for n in st["nodes"]]
    assert "dai_defense_llm" in ids
    assert "dai_dual_path_analyze" in ids
    assert ids.index("dai_defense_llm") < ids.index("replan_llm")


def test_chat_init_has_five_base_nodes() -> None:
    ctx = SkillContext(user_input="")
    init_pipeline_run(ctx, "chat")
    st = get_pipeline_status(ctx)
    assert len(st["nodes"]) == 5
    assert st["nodes"][0]["id"] == "ingress"


def test_review_init_includes_dai_dag() -> None:
    ctx = SkillContext(user_input="")
    init_pipeline_run(ctx, "review")
    st = get_pipeline_status(ctx)
    ids = [n["id"] for n in st["nodes"]]
    assert "dai_defense_llm" in ids
    assert "dai_dual_path_analyze" in ids
    assert "finish" in ids


def test_advance_pipeline_node_updates_current() -> None:
    ctx = SkillContext(user_input="")
    init_pipeline_run(ctx, "chat")
    advance_pipeline_node(ctx, "planner_llm", model="qwen2.5:7b")
    st = get_pipeline_status(ctx)
    assert st["current_node_id"] == "planner_llm"
    assert "7b" in st["headline_zh"]
    active = [n for n in st["nodes"] if n["status"] == "active"]
    assert len(active) == 1
    assert active[0]["id"] == "planner_llm"


def test_splice_dai_only_once() -> None:
    ctx = SkillContext(user_input="")
    init_pipeline_run(ctx, "chat")
    splice_dai_nodes(ctx)
    n1 = len(get_pipeline_status(ctx)["nodes"])
    splice_dai_nodes(ctx)
    n2 = len(get_pipeline_status(ctx)["nodes"])
    assert n1 == n2
    assert n1 == 5 + 2  # chat 5 + dai_defense_llm + dual_path_analyze
