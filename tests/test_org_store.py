"""組織圖譜 store 載入測試（Phase V0）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from dual_agent.dai.org.layout import layout_org_hierarchy
from dual_agent.dai.org.schemas import org_graph_from_dict
from dual_agent.dai.org.store import get_default_org_path, load_org_graph


def test_example_org_file_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    example = root / "data" / "org" / "org_graph.example.json"
    assert example.is_file()


def test_load_org_graph_from_example() -> None:
    root = Path(__file__).resolve().parents[1]
    example = root / "data" / "org" / "org_graph.example.json"
    graph = load_org_graph(example)
    assert graph.root_employee_id == "emp_ceo"
    assert len(graph.employees) >= 8
    assert len(graph.departments) >= 3
    reports = graph.list_direct_reports("emp_ceo")
    assert "emp_product_head" in reports
    assert "emp_eng_head" in reports


def test_get_default_org_path_finds_example() -> None:
    path = get_default_org_path()
    assert path is not None
    assert path.name in ("org_graph.json", "org_graph.example.json")


def test_layout_org_hierarchy_positions_all_employees() -> None:
    graph = load_org_graph()
    layout = layout_org_hierarchy(graph)
    assert set(layout.nodes.keys()) == set(graph.employees.keys())
    assert layout.canvas_width > 0
    assert layout.canvas_height > 0
    root = layout.nodes[graph.root_employee_id]
    for node in layout.nodes.values():
        if node.employee_id != graph.root_employee_id:
            assert node.y > root.y


def test_org_graph_from_dict_infers_root() -> None:
    raw = {
        "employees": {
            "a": {"id": "a", "name": "Boss"},
            "b": {"id": "b", "name": "Staff"},
        },
        "edges": [{"from": "b", "to": "a", "type": "reports_to"}],
    }
    graph = org_graph_from_dict(raw)
    assert graph.root_employee_id == "a"
