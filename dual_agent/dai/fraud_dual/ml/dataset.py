"""從 tw_sms_5k_persona.csv 載入訓練樣本。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from dual_agent.dai.fraud_dual.shared.constants import SCAM_TYPES

DEFAULT_PERSONA_CSV = Path(
    r"c:\Users\labpc\Desktop\dataset\Telecom_Fraud_Texts_5\tw_sms_5k_persona.csv"
)


@dataclass
class ThreatSample:
    text: str
    scam_type: str
    threat_score: float
    age_band: str
    occupation: str
    relation_type: str
    channel: str
    primary_apps: tuple[str, ...]
    invest_exp: str | None
    persona_role: str
    context_score: float | None = None


@dataclass
class ContextSample:
    text: str
    scam_type: str
    threat_score: float
    age_band: str
    occupation: str
    relation_type: str
    channel: str
    primary_apps: tuple[str, ...]
    invest_exp: str | None
    persona_role: str
    context_score: float
    channel_is_familiar: int


def _parse_apps(raw: str) -> tuple[str, ...]:
    apps = tuple(a.strip() for a in (raw or "").split("|") if a.strip())
    return apps or ("LINE",)


def load_persona_csv(path: Path | None = None) -> list[dict[str, str]]:
    path = Path(path or DEFAULT_PERSONA_CSV)
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_threat_samples(
    path: Path | None = None,
    *,
    prefer_role: str = "neutral",
) -> list[ThreatSample]:
    """
    Threat 用「每則訊息一筆」避免同一本文三倍灌權重。
    優先取 prefer_role；否則取該 content 的第一筆。
    """
    rows = load_persona_csv(path)
    by_content: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        by_content.setdefault(r["content"], []).append(r)

    out: list[ThreatSample] = []
    for content, group in by_content.items():
        chosen = next((g for g in group if g.get("persona_role") == prefer_role), group[0])
        label = chosen["label"]
        if label not in SCAM_TYPES:
            continue
        invest = (chosen.get("invest_exp") or "").strip() or None
        out.append(
            ThreatSample(
                text=content,
                scam_type=label,
                threat_score=float(chosen.get("threat_score") or 0.0),
                age_band=chosen["age_band"],
                occupation=chosen["occupation"],
                relation_type=chosen["relation_type"],
                channel=chosen["channel"],
                primary_apps=_parse_apps(chosen.get("primary_apps", "LINE")),
                invest_exp=invest,
                persona_role=chosen.get("persona_role", prefer_role),
                context_score=(
                    float(chosen["context_score"])
                    if chosen.get("context_score") not in (None, "")
                    else None
                ),
            )
        )
    return out


def load_context_samples(path: Path | None = None) -> list[ContextSample]:
    """Context 用全部人設列（同文三對照）。"""
    rows = load_persona_csv(path)
    out: list[ContextSample] = []
    for r in rows:
        label = r["label"]
        if label not in SCAM_TYPES:
            continue
        if r.get("context_score") in (None, ""):
            continue
        invest = (r.get("invest_exp") or "").strip() or None
        out.append(
            ContextSample(
                text=r["content"],
                scam_type=label,
                threat_score=float(r.get("threat_score") or 0.0),
                age_band=r["age_band"],
                occupation=r["occupation"],
                relation_type=r["relation_type"],
                channel=r["channel"],
                primary_apps=_parse_apps(r.get("primary_apps", "LINE")),
                invest_exp=invest,
                persona_role=r.get("persona_role", ""),
                context_score=float(r["context_score"]),
                channel_is_familiar=int(float(r.get("channel_is_familiar") or 0)),
            )
        )
    return out
