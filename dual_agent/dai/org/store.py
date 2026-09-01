"""組織圖譜 JSON 載入（Phase V0）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dual_agent.dai.org.schemas import OrgGraph, org_graph_from_dict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ORG_DIR = _REPO_ROOT / "data" / "org"
_DEFAULT_FILES = ("org_graph.json", "org_graph.example.json")


def get_org_data_dir() -> Path:
    return _ORG_DIR


def get_default_org_path() -> Path | None:
    for name in _DEFAULT_FILES:
        path = _ORG_DIR / name
        if path.is_file():
            return path
    return None


def load_org_graph(path: str | Path | None = None) -> OrgGraph:
    target = Path(path) if path is not None else get_default_org_path()
    if target is None or not target.is_file():
        raise FileNotFoundError(
            f"找不到組織圖譜資料檔。請在 {_ORG_DIR} 放置 "
            + " 或 ".join(_DEFAULT_FILES)
        )
    raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    graph = org_graph_from_dict(raw)
    if not graph.employees:
        raise ValueError(f"組織圖譜為空：{target}")
    return graph
