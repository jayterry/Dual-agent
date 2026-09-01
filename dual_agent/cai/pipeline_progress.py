"""CAI / Review 管線階段與流程圖節點，供手機端輪詢 GET /v1/session/{id}/pipeline。"""

from __future__ import annotations

import time
from typing import Any, Literal

from dual_agent.config import OLLAMA_MODEL, cai_memory_model
from dual_agent.skill_types import SkillContext

PipelineFlow = Literal["chat", "review"]
StepStatus = Literal["pending", "active", "done"]
NodeKind = Literal["system", "llm", "skill", "dai_step"]

CHAT_STAGES: list[tuple[str, str]] = [
    ("ingress", "理解訊息"),
    ("memory", "記憶判斷"),
    ("planner", "規劃任務"),
    ("execute", "執行技能"),
    ("replan", "整理回覆"),
]

REVIEW_STAGES: list[tuple[str, str]] = [
    ("dai", "雙路風險分析"),
    ("replan", "整理回覆"),
    ("finish", "完成"),
]

_STAGE_TO_NODE: dict[str, str] = {
    "ingress": "ingress",
    "memory": "memory_llm",
    "planner": "planner_llm",
    "execute": "executor_skill",
    "replan": "replan_llm",
    "dai": "dai_plan",
    "finish": "finish",
}

_DAI_STEP_LABELS: dict[str, str] = {
    "dual_path_analyze": "雙路風險分析",
    "build_analysis_payload": "建構分析載荷",
    "score_rules": "規則評分",
    "score_threat_intel": "威脅情資",
    "score_tls": "TLS 檢查",
    "score_toxic": "毒樣分析",
    "semantic_supplement": "語意補充",
    "fuse_risk_and_ueba": "融合與 UEBA",
}

# 雙路主路徑流程圖子節點（不再顯示舊 7 步 DAG）
_DUAL_FLOW_NODE_SPECS: list[tuple[str, NodeKind, str]] = [
    ("dai_infer", "system", "推斷管道／關係"),
    ("dai_path_a", "dai_step", "Path A 威脅／情境"),
    ("dai_path_b", "dai_step", "Path B（LLM）"),
    ("dai_narrator", "llm", "Narrator 說明"),
]

_DAI_LLM_STEPS: frozenset[str] = frozenset(
    {"dual_path_analyze", "score_toxic", "semantic_supplement", "dai_path_b", "dai_narrator"}
)

_SKILL_LABELS: dict[str, str] = {
    "call_dai": "風險分析",
    "ask_user": "詢問使用者",
    "search_web": "網路搜尋",
    "open_url_readonly": "開啟網頁",
    "fetch_url": "抓取網頁",
    "weather": "天氣查詢",
    "memory_recall": "記憶回想",
    "noop": "略過",
}


def _new_node(
    *,
    node_id: str,
    kind: NodeKind,
    label_zh: str,
    status: StepStatus = "pending",
    model: str = "",
    skill: str = "",
) -> dict[str, str]:
    return {
        "id": node_id,
        "kind": kind,
        "label_zh": label_zh,
        "model": (model or "").strip(),
        "skill": (skill or "").strip(),
        "status": status,
    }


def _chat_base_nodes() -> list[dict[str, str]]:
    return [
        _new_node(node_id="ingress", kind="system", label_zh="載入記憶與上下文"),
        _new_node(node_id="memory_llm", kind="llm", label_zh="Memory Manager"),
        _new_node(node_id="planner_llm", kind="llm", label_zh="Planner"),
        _new_node(node_id="executor_skill", kind="skill", label_zh="執行技能"),
        _new_node(node_id="replan_llm", kind="llm", label_zh="Replan"),
    ]


def _dual_flow_nodes() -> list[dict[str, str]]:
    return [
        _new_node(node_id=nid, kind=kind, label_zh=label)
        for nid, kind, label in _DUAL_FLOW_NODE_SPECS
    ]


def _review_base_nodes() -> list[dict[str, str]]:
    nodes = [
        _new_node(node_id="ingress", kind="system", label_zh="載入記憶與上下文"),
        _new_node(node_id="dai_plan", kind="llm", label_zh="DAI 啟動"),
    ]
    nodes.extend(_dual_flow_nodes())
    nodes.append(_new_node(node_id="replan_llm", kind="llm", label_zh="Replan"))
    nodes.append(_new_node(node_id="finish", kind="system", label_zh="完成"))
    return nodes


def _dai_sub_nodes() -> list[dict[str, str]]:
    nodes = [_new_node(node_id="dai_plan", kind="llm", label_zh="DAI 啟動")]
    nodes.extend(_dual_flow_nodes())
    return nodes


def _get_pipe(ctx: SkillContext) -> dict[str, Any]:
    raw = ctx.policy_state.get("pipeline")
    if not isinstance(raw, dict):
        raw = {}
        ctx.policy_state["pipeline"] = raw
    return raw


def init_pipeline_run(ctx: SkillContext, flow: PipelineFlow) -> None:
    """請求開始時建立本輪流程圖節點列表。"""
    nodes = _review_base_nodes() if flow == "review" else _chat_base_nodes()
    ctx.policy_state["pipeline"] = {
        "flow": flow,
        "stage": "",
        "detail": "",
        "label_zh": "",
        "nodes": nodes,
        "current_node_id": "",
        "dai_spliced": flow == "review",
        "headline_zh": "準備中…",
        "updated_at": time.time(),
    }


def _node_index(nodes: list[dict[str, str]], node_id: str) -> int:
    for i, n in enumerate(nodes):
        if n.get("id") == node_id:
            return i
    return -1


def _build_headline(node: dict[str, str]) -> str:
    kind = str(node.get("kind") or "")
    label = str(node.get("label_zh") or "")
    model = str(node.get("model") or "").strip()
    skill = str(node.get("skill") or "").strip()
    if kind == "llm" and model:
        return f"{label} · {model}"
    if kind == "skill":
        sk_label = _SKILL_LABELS.get(skill, skill) if skill else ""
        return f"{label} · {sk_label}" if sk_label else label
    if kind == "dai_step" and model:
        return f"{label} · {model}"
    return label


def splice_dai_nodes(ctx: SkillContext) -> None:
    """Chat 路徑進入 call_dai 時，在 executor 與 replan 之間插入 DAI 子流程。"""
    pipe = _get_pipe(ctx)
    if pipe.get("dai_spliced"):
        return
    nodes = list(pipe.get("nodes") or [])
    if not nodes:
        return
    replan_idx = _node_index(nodes, "replan_llm")
    if replan_idx < 0:
        nodes.extend(_dai_sub_nodes())
    else:
        insert_at = replan_idx
        for i, sub in enumerate(_dai_sub_nodes()):
            nodes.insert(insert_at + i, sub)
    pipe["nodes"] = nodes
    pipe["dai_spliced"] = True
    pipe["updated_at"] = time.time()


def advance_pipeline_node(
    ctx: SkillContext,
    node_id: str,
    *,
    model: str = "",
    skill: str = "",
) -> None:
    """將目標節點標為 active，其前為 done，其後為 pending。"""
    pipe = _get_pipe(ctx)
    nodes = pipe.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return
    idx = _node_index(nodes, node_id)
    if idx < 0:
        return
    m = (model or "").strip()
    sk = (skill or "").strip()
    for i, n in enumerate(nodes):
        if i < idx:
            n["status"] = "done"
        elif i == idx:
            n["status"] = "active"
            if m:
                n["model"] = m
            if sk:
                n["skill"] = sk
                sk_label = _SKILL_LABELS.get(sk, sk)
                n["label_zh"] = f"執行 · {sk_label}"
        else:
            n["status"] = "pending"
            if n.get("kind") == "skill" and n.get("id") == "executor_skill":
                n["label_zh"] = "執行技能"
                n["skill"] = ""
    pipe["current_node_id"] = node_id
    pipe["headline_zh"] = _build_headline(nodes[idx])
    pipe["updated_at"] = time.time()


def _stage_index(flow: PipelineFlow, stage: str) -> int:
    table = CHAT_STAGES if flow == "chat" else REVIEW_STAGES
    for i, (sid, _) in enumerate(table):
        if sid == stage:
            return i
    return 0


def _label_for_stage(flow: PipelineFlow, stage: str) -> str:
    table = CHAT_STAGES if flow == "chat" else REVIEW_STAGES
    for sid, label in table:
        if sid == stage:
            return label
    return stage


def detail_label_zh(detail: str) -> str:
    d = (detail or "").strip()
    if not d:
        return ""
    return _SKILL_LABELS.get(d, d)


def set_pipeline_stage(
    ctx: SkillContext,
    *,
    flow: PipelineFlow,
    stage: str,
    detail: str = "",
    model: str = "",
) -> None:
    """粗粒度 stage（向後相容）+ 流程圖節點推進。"""
    pipe = _get_pipe(ctx)
    if not pipe.get("nodes"):
        init_pipeline_run(ctx, flow)
        pipe = _get_pipe(ctx)

    label = _label_for_stage(flow, stage)
    d = (detail or "").strip()
    m = (model or "").strip()

    pipe["flow"] = flow
    pipe["stage"] = stage
    pipe["detail"] = d
    pipe["label_zh"] = label
    pipe["updated_at"] = time.time()

    node_id = _STAGE_TO_NODE.get(stage, stage)
    if stage == "execute" and d == "call_dai":
        splice_dai_nodes(ctx)
        pipe = _get_pipe(ctx)

    if stage == "execute":
        advance_pipeline_node(ctx, "executor_skill", model=m or OLLAMA_MODEL, skill=d)
    elif node_id:
        default_model = ""
        if node_id == "memory_llm":
            default_model = m or cai_memory_model()
        elif node_id in ("planner_llm", "replan_llm", "dai_plan", "dai_defense_llm", "dai_narrator"):
            default_model = m or OLLAMA_MODEL
        advance_pipeline_node(ctx, node_id, model=default_model, skill=d if node_id == "executor_skill" else "")


def advance_dai_step(ctx: SkillContext, step_name: str, *, model: str = "") -> None:
    """DAI Executor 步驟：舊 DAG 對應 dai_{name}；雙路主路徑進到第一個子節點。"""
    m = (model or "").strip()
    if step_name == "dual_path_analyze":
        # 細節進度由 advance_dual_phase 在分析中間推進
        advance_pipeline_node(ctx, "dai_infer", model=m)
        return
    node_id = f"dai_{step_name}"
    if not m and step_name in _DAI_LLM_STEPS:
        m = OLLAMA_MODEL
    advance_pipeline_node(ctx, node_id, model=m)


def advance_dual_phase(
    ctx: SkillContext | None,
    phase: str,
    *,
    model: str = "",
) -> None:
    """雙路分析內部階段：infer / path_a / path_b / narrator。"""
    if ctx is None:
        return
    mapping = {
        "infer": "dai_infer",
        "path_a": "dai_path_a",
        "path_b": "dai_path_b",
        "narrator": "dai_narrator",
    }
    node_id = mapping.get(phase)
    if not node_id:
        return
    m = (model or "").strip()
    if not m and node_id in ("dai_path_b", "dai_narrator"):
        m = OLLAMA_MODEL
    advance_pipeline_node(ctx, node_id, model=m)


def clear_pipeline_stage(ctx: SkillContext) -> None:
    ctx.policy_state.pop("pipeline", None)


def build_step_list(flow: PipelineFlow, current_stage: str) -> list[dict[str, str]]:
    table = CHAT_STAGES if flow == "chat" else REVIEW_STAGES
    idx = _stage_index(flow, current_stage)
    steps: list[dict[str, str]] = []
    for i, (sid, label) in enumerate(table):
        if i < idx:
            status: StepStatus = "done"
        elif i == idx:
            status = "active"
        else:
            status = "pending"
        steps.append({"id": sid, "label_zh": label, "status": status})
    return steps


def get_pipeline_status(ctx: SkillContext) -> dict[str, Any]:
    raw = ctx.policy_state.get("pipeline")
    if not isinstance(raw, dict) or not raw.get("flow"):
        return {
            "flow": "",
            "stage": "",
            "detail": "",
            "label_zh": "準備中…",
            "detail_label_zh": "",
            "headline_zh": "準備中…",
            "steps": [],
            "nodes": [],
            "current_node_id": "",
            "current_index": -1,
        }
    flow = str(raw.get("flow") or "")
    if flow not in ("chat", "review"):
        flow = "chat"
    stage = str(raw.get("stage") or "")
    detail = str(raw.get("detail") or "")
    label_zh = str(raw.get("label_zh") or _label_for_stage(flow, stage))  # type: ignore[arg-type]
    detail_label = detail_label_zh(detail)
    idx = _stage_index(flow, stage)  # type: ignore[arg-type]
    steps = build_step_list(flow, stage)  # type: ignore[arg-type]
    nodes = list(raw.get("nodes") or [])
    current_node_id = str(raw.get("current_node_id") or "")
    headline_zh = str(raw.get("headline_zh") or label_zh)
    return {
        "flow": flow,
        "stage": stage,
        "detail": detail,
        "label_zh": label_zh,
        "detail_label_zh": detail_label,
        "headline_zh": headline_zh,
        "steps": steps,
        "nodes": nodes,
        "current_node_id": current_node_id,
        "current_index": idx,
    }
