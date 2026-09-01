"""組織圖譜資料模型（Phase V0：供視覺化與日後查詢共用）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OrgEdgeType = Literal["reports_to", "member_of"]


@dataclass
class DepartmentNode:
    id: str
    name: str


@dataclass
class EmployeeNode:
    id: str
    name: str
    title: str = ""
    department_id: str = ""


@dataclass
class OrgEdge:
    from_id: str
    to_id: str
    type: OrgEdgeType = "reports_to"


@dataclass
class OrgGraph:
    version: int = 1
    departments: dict[str, DepartmentNode] = field(default_factory=dict)
    employees: dict[str, EmployeeNode] = field(default_factory=dict)
    edges: list[OrgEdge] = field(default_factory=list)
    root_employee_id: str = ""

    def get_manager_id(self, employee_id: str) -> str | None:
        for edge in self.edges:
            if edge.type == "reports_to" and edge.from_id == employee_id:
                return edge.to_id
        return None

    def list_direct_reports(self, manager_id: str) -> list[str]:
        out: list[str] = []
        for edge in self.edges:
            if edge.type == "reports_to" and edge.to_id == manager_id:
                out.append(edge.from_id)
        return out

    def department_name(self, department_id: str) -> str:
        dept = self.departments.get(department_id)
        return dept.name if dept else department_id


def org_graph_from_dict(raw: dict[str, Any]) -> OrgGraph:
    departments: dict[str, DepartmentNode] = {}
    for key, item in (raw.get("departments") or {}).items():
        if not isinstance(item, dict):
            continue
        dept_id = str(item.get("id") or key).strip()
        if not dept_id:
            continue
        departments[dept_id] = DepartmentNode(
            id=dept_id,
            name=str(item.get("name") or dept_id).strip(),
        )

    employees: dict[str, EmployeeNode] = {}
    for key, item in (raw.get("employees") or {}).items():
        if not isinstance(item, dict):
            continue
        emp_id = str(item.get("id") or key).strip()
        if not emp_id:
            continue
        employees[emp_id] = EmployeeNode(
            id=emp_id,
            name=str(item.get("name") or emp_id).strip(),
            title=str(item.get("title") or "").strip(),
            department_id=str(item.get("department_id") or "").strip(),
        )

    edges: list[OrgEdge] = []
    for item in raw.get("edges") or []:
        if not isinstance(item, dict):
            continue
        from_id = str(item.get("from") or item.get("from_id") or "").strip()
        to_id = str(item.get("to") or item.get("to_id") or "").strip()
        if not from_id or not to_id:
            continue
        edge_type = str(item.get("type") or "reports_to").strip()
        if edge_type not in ("reports_to", "member_of"):
            edge_type = "reports_to"
        edges.append(OrgEdge(from_id=from_id, to_id=to_id, type=edge_type))  # type: ignore[arg-type]

    root = str(raw.get("root_employee_id") or "").strip()
    if not root and employees:
        managed = {e.from_id for e in edges if e.type == "reports_to"}
        managers = {e.to_id for e in edges if e.type == "reports_to"}
        roots = [eid for eid in employees if eid in managers and eid not in managed]
        if len(roots) == 1:
            root = roots[0]
        elif managers:
            top = managers - managed
            if len(top) == 1:
                root = next(iter(top))

    try:
        version = int(raw.get("version") or 1)
    except (TypeError, ValueError):
        version = 1

    return OrgGraph(
        version=version,
        departments=departments,
        employees=employees,
        edges=edges,
        root_employee_id=root,
    )


def org_graph_to_dict(graph: OrgGraph) -> dict[str, Any]:
    return {
        "version": graph.version,
        "root_employee_id": graph.root_employee_id,
        "departments": {
            did: {"id": d.id, "name": d.name} for did, d in graph.departments.items()
        },
        "employees": {
            eid: {
                "id": e.id,
                "name": e.name,
                "title": e.title,
                "department_id": e.department_id,
            }
            for eid, e in graph.employees.items()
        },
        "edges": [
            {"from": e.from_id, "to": e.to_id, "type": e.type} for e in graph.edges
        ],
    }
