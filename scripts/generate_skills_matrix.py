#!/usr/bin/env python3
"""Generate docs/SKILLS_MATRIX.md from registry + Agent Skills Added.md."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dual_agent.skills_registry import SKILLS

MD_PATH = ROOT / "Agent Skills Added.md"
OUT_PATH = ROOT / "docs" / "SKILLS_MATRIX.md"

# Catalog name -> registry name (when names differ)
CATALOG_TO_REGISTRY: dict[str, str] = {
    "open_url": "open_url_readonly",
    "risk_analysis": "run_guard_pipeline",
    "call_dai": "call_dai",
}

# Implemented via pipeline / module, not a separate registry skill
PIPELINE_IMPL: dict[str, str] = {
    "risk_analysis": "dual_agent/dai/risk_analysis (run_risk_analysis)",
    "extract_urls": "risk_analysis URL extraction",
    "check_url_reputation": "risk_analysis providers (placeholder)",
    "content_moderation": "toxic_score / Chroma",
    "pii_detection": "rules.py partial (ID patterns)",
}


def _parse_md_tables(md: str) -> dict[str, list[tuple[str, str]]]:
    """Return {section_key: [(skill_name, purpose), ...]}."""
    sections: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for line in md.splitlines():
        if line.startswith("## 1"):
            current = "cai"
            sections[current] = []
            continue
        if line.startswith("## 2"):
            current = "dai"
            sections[current] = []
            continue
        if line.startswith("## 3"):
            current = "hybrid"
            sections[current] = []
            continue
        if line.startswith("## 4"):
            current = "advanced"
            sections[current] = []
            continue
        if current and line.startswith("|") and not line.startswith("| ---"):
            if "Skill Name" in line or "Feature Name" in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 4:
                continue
            name = parts[1].replace("\\", "").strip()
            purpose = parts[2].strip()
            if name and name != "-----":
                sections[current].append((name, purpose))
    return sections


def _partition_registry() -> tuple[list[str], list[str], dict[str, str]]:
    cai: list[str] = []
    dai: list[str] = []
    aliases: dict[str, str] = {}
    for spec in SKILLS.values():
        norm = os.path.normpath(spec.skill_dir or "").lower()
        bucket = dai if f"{os.sep}dai{os.sep}skills{os.sep}" in norm + os.sep else cai
        bucket.append(spec.name)
        for alias in spec.aliases or []:
            aliases[alias] = spec.name
    return sorted(cai), sorted(dai), aliases


def _registry_set(cai: list[str], dai: list[str], aliases: dict[str, str]) -> set[str]:
    names = set(cai) | set(dai) | set(aliases.keys()) | set(aliases.values())
    return names


def _status(catalog_name: str, registry: set[str]) -> tuple[str, str]:
    reg = CATALOG_TO_REGISTRY.get(catalog_name, catalog_name)
    if reg in registry or catalog_name in registry:
        note = "registry"
        if catalog_name in PIPELINE_IMPL:
            note = PIPELINE_IMPL[catalog_name]
        return "已實作", note
    if catalog_name in PIPELINE_IMPL:
        return "已實作（管線）", PIPELINE_IMPL[catalog_name]
    if catalog_name in CATALOG_TO_REGISTRY and CATALOG_TO_REGISTRY[catalog_name] in registry:
        return "已實作", f"registry as `{CATALOG_TO_REGISTRY[catalog_name]}`"
    return "規劃中", "—"


def _extra_registry_rows(
    registry: set[str],
    catalog_names: set[str],
    cai: list[str],
    dai: list[str],
    aliases: dict[str, str],
) -> list[tuple[str, str, str, str]]:
    """Skills in registry but not in catalog MD."""
    mapped_catalog = {CATALOG_TO_REGISTRY.get(c, c) for c in catalog_names}
    mapped_catalog |= catalog_names
    extras: list[tuple[str, str, str, str]] = []
    for name in cai:
        if name not in mapped_catalog and name not in catalog_names:
            extras.append((name, "—", "已實作", "registry only (CAI)"))
    for name in dai:
        if name not in mapped_catalog and name not in catalog_names:
            extras.append((name, "—", "已實作", "registry only (DAI)"))
    for alias, canonical in sorted(aliases.items()):
        if alias not in catalog_names and canonical not in mapped_catalog:
            extras.append((alias, "—", "已實作", f"alias → `{canonical}`"))
    return extras


def generate() -> str:
    md_text = MD_PATH.read_text(encoding="utf-8")
    sections = _parse_md_tables(md_text)
    cai_names, dai_names, skill_aliases = _partition_registry()
    registry = _registry_set(cai_names, dai_names, skill_aliases)
    all_catalog = {n for rows in sections.values() for n, _ in rows}

    lines: list[str] = [
        "# Dual-agent Skills 對照矩陣",
        "",
        "本文件由 `scripts/generate_skills_matrix.py` 自動產生，對照：",
        "",
        "- **Catalog**：[`Agent Skills Added.md`](../Agent%20Skills%20Added.md)",
        "- **Registry**：`dual_agent/cai/skills_registry.py`",
        "",
        f"產生時間（UTC）：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 摘要",
        "",
        f"| 指標 | 數值 |",
        f"|------|------|",
        f"| CAI registry | {len(cai_names)} |",
        f"| DAI registry | {len(dai_names)} |",
        f"| Catalog CAI 列 | {len(sections.get('cai', []))} |",
        f"| Catalog DAI 列 | {len(sections.get('dai', []))} |",
        "",
        "**狀態**：`已實作` = registry 或 risk_analysis 管線；`規劃中` = 僅出現在 Catalog。",
        "",
    ]

    section_titles = {
        "cai": "## 1. Helpful (CAI)",
        "dai": "## 2. Protective (DAI)",
        "hybrid": "## 3. Hybrid / Patterns",
        "advanced": "## 4. Advanced Features",
    }

    for key, title in section_titles.items():
        rows = sections.get(key, [])
        if not rows:
            continue
        lines.extend([title, "", "| Catalog 名稱 | 用途（摘要） | 狀態 | 備註 |", "|-------------|-------------|------|------|"])
        for name, purpose in rows:
            purpose_short = (purpose[:60] + "…") if len(purpose) > 60 else purpose
            purpose_short = purpose_short.replace("|", "\\|")
            status, note = _status(name, registry)
            lines.append(f"| `{name}` | {purpose_short} | {status} | {note} |")
        lines.append("")

    extras = _extra_registry_rows(registry, all_catalog, cai_names, dai_names, skill_aliases)
    if extras:
        lines.extend(
            [
                "## 5. Registry 有、Catalog 未列",
                "",
                "| 名稱 | 用途 | 狀態 | 備註 |",
                "|------|------|------|------|",
            ]
        )
        for name, purpose, status, note in extras:
            lines.append(f"| `{name}` | {purpose} | {status} | {note} |")
        lines.append("")

    lines.extend(
        [
            "## 重新產生",
            "",
            "```bash",
            "python scripts/generate_skills_matrix.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = generate()
    OUT_PATH.write_text(content, encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
