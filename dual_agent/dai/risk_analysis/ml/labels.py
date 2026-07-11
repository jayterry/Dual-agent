"""標註資料 JSONL schema 與讀寫。"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

LabelClass = Literal["scam", "benign", "suspicious"]
SplitName = Literal["train", "val", "test"]
VerdictGt = Literal["allow", "warn", "block"]


@dataclass
class LabelRecord:
    id: str
    text: str
    source: str = "seed"
    label: LabelClass = "benign"
    verdict_gt: str = ""
    fraud_types_gt: list[str] = field(default_factory=list)
    annotator: str = "seed"
    split: SplitName = "train"
    notes: str = ""

    def to_jsonl_row(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> LabelRecord:
        label = str(raw.get("label") or "benign").strip().lower()
        if label not in ("scam", "benign", "suspicious"):
            label = "benign"
        split = str(raw.get("split") or "train").strip().lower()
        if split not in ("train", "val", "test"):
            split = "train"
        ft = raw.get("fraud_types_gt") or raw.get("fraud_types") or []
        if not isinstance(ft, list):
            ft = []
        return cls(
            id=str(raw.get("id") or uuid.uuid4()),
            text=str(raw.get("text") or "").strip(),
            source=str(raw.get("source") or "seed").strip() or "seed",
            label=label,  # type: ignore[arg-type]
            verdict_gt=str(raw.get("verdict_gt") or "").strip(),
            fraud_types_gt=[str(x) for x in ft if str(x).strip()],
            annotator=str(raw.get("annotator") or "seed").strip() or "seed",
            split=split,  # type: ignore[arg-type]
            notes=str(raw.get("notes") or "").strip(),
        )


def load_labels_jsonl(path: str | Path) -> list[LabelRecord]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    out: list[LabelRecord] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(LabelRecord.from_dict(json.loads(line)))
    return out


def write_labels_jsonl(path: str | Path, records: list[LabelRecord]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r.to_jsonl_row(), ensure_ascii=False) for r in records]
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
