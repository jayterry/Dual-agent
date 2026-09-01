"""組織圖層級布局（自上而下匯報線）。"""

from __future__ import annotations

from dataclasses import dataclass

from dual_agent.dai.org.schemas import OrgGraph

NODE_WIDTH = 120.0
NODE_HEIGHT = 52.0
H_GAP = 36.0
V_GAP = 72.0
MARGIN_X = 40.0
MARGIN_Y = 40.0


@dataclass(frozen=True)
class NodeLayout:
    employee_id: str
    x: float
    y: float
    width: float = NODE_WIDTH
    height: float = NODE_HEIGHT

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height


@dataclass(frozen=True)
class OrgLayoutResult:
    nodes: dict[str, NodeLayout]
    canvas_width: float
    canvas_height: float


def _subtree_width(graph: OrgGraph, employee_id: str, memo: dict[str, float]) -> float:
    if employee_id in memo:
        return memo[employee_id]
    reports = graph.list_direct_reports(employee_id)
    if not reports:
        memo[employee_id] = NODE_WIDTH
        return NODE_WIDTH
    total = sum(_subtree_width(graph, rid, memo) for rid in reports)
    total += H_GAP * max(0, len(reports) - 1)
    memo[employee_id] = max(NODE_WIDTH, total)
    return memo[employee_id]


def _place_subtree(
    graph: OrgGraph,
    employee_id: str,
    depth: int,
    left: float,
    memo: dict[str, float],
    positions: dict[str, NodeLayout],
) -> float:
    width = memo.get(employee_id) or _subtree_width(graph, employee_id, memo)
    x = left + (width - NODE_WIDTH) / 2
    y = MARGIN_Y + depth * (NODE_HEIGHT + V_GAP)
    positions[employee_id] = NodeLayout(employee_id=employee_id, x=x, y=y)

    reports = graph.list_direct_reports(employee_id)
    if not reports:
        return left + width

    cursor = left
    for rid in reports:
        child_w = memo.get(rid) or _subtree_width(graph, rid, memo)
        cursor = _place_subtree(graph, rid, depth + 1, cursor, memo, positions)
        cursor += H_GAP
    return left + width


def layout_org_hierarchy(graph: OrgGraph) -> OrgLayoutResult:
    root_id = graph.root_employee_id
    if not root_id or root_id not in graph.employees:
        raise ValueError("組織圖缺少有效的 root_employee_id")

    memo: dict[str, float] = {}
    _subtree_width(graph, root_id, memo)
    positions: dict[str, NodeLayout] = {}
    _place_subtree(graph, root_id, 0, MARGIN_X, memo, positions)

    max_x = max((n.x + n.width for n in positions.values()), default=NODE_WIDTH)
    max_y = max((n.y + n.height for n in positions.values()), default=NODE_HEIGHT)
    return OrgLayoutResult(
        nodes=positions,
        canvas_width=max_x + MARGIN_X,
        canvas_height=max_y + MARGIN_Y,
    )
