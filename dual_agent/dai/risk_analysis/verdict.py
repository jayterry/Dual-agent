"""verdict 與 dominant_source。"""

from __future__ import annotations

from dataclasses import dataclass

from dual_agent.config import dai_risk_llm_weight

_LLM_RAW_CAP = 32
_UEBA_DELTA_POS_CAP = 15
_UEBA_DELTA_NEG_CAP = -8


@dataclass(frozen=True)
class MachineFusionParts:
    r_machine_base: int
    r_machine_support_bonus: int
    r_machine_final: int


@dataclass(frozen=True)
class RiskFusionResult:
    r_fused: int
    r_llm_100: int
    machine: MachineFusionParts
    hard_guard_applied: bool


def verdict_from_score(score: int) -> str:
    s = int(score)
    if s >= 85:
        return "block"
    if s >= 70:
        return "warn"
    return "allow"


def scale_llm_score_to_100(
    r_llm_optional: int,
    *,
    tier_h: int = 0,
    tier_i: int = 0,
) -> int:
    """將語意層 0–32 分映射到 0–100，供加權融合使用。"""
    raw = max(int(r_llm_optional or 0), int(tier_h or 0) + int(tier_i or 0))
    raw = max(0, min(_LLM_RAW_CAP, raw))
    if raw <= 0:
        return 0
    return min(100, max(0, round(raw * 100 / _LLM_RAW_CAP)))


def compute_r_machine(
    *,
    r_rules: int,
    r_threat_intel: int,
    r_tls: int,
    r_toxic_fused: int,
) -> MachineFusionParts:
    """機器層：最高分 + 次高分／第三高分支援加成。"""
    scores = sorted(
        [
            int(r_rules or 0),
            int(r_threat_intel or 0),
            int(r_tls or 0),
            int(r_toxic_fused or 0),
        ],
        reverse=True,
    )
    base = scores[0]
    second = scores[1] if len(scores) > 1 else 0
    third = scores[2] if len(scores) > 2 else 0
    support_bonus = round(0.15 * second + 0.10 * third)
    final = max(0, min(100, base + support_bonus))
    return MachineFusionParts(
        r_machine_base=base,
        r_machine_support_bonus=support_bonus,
        r_machine_final=final,
    )


def fuse_risk_score_weighted(
    *,
    r_rules: int,
    r_threat_intel: int,
    r_tls: int,
    r_toxic_fused: int,
    r_llm_optional: int,
    tier_h: int = 0,
    tier_i: int = 0,
    llm_weight: float | None = None,
) -> RiskFusionResult:
    """
    加權融合：預設語意層 35%、機器層 65%（含支援加成後的 r_machine_final）。
    """
    w_llm = dai_risk_llm_weight() if llm_weight is None else float(llm_weight)
    w_llm = max(0.0, min(1.0, w_llm))
    w_machine = 1.0 - w_llm

    machine = compute_r_machine(
        r_rules=r_rules,
        r_threat_intel=r_threat_intel,
        r_tls=r_tls,
        r_toxic_fused=r_toxic_fused,
    )
    r_llm_100 = scale_llm_score_to_100(r_llm_optional, tier_h=tier_h, tier_i=tier_i)

    fused = round(w_machine * machine.r_machine_final + w_llm * r_llm_100)
    fused = max(0, min(100, fused))
    hard_guard_applied = False

    hard = max(int(r_rules or 0), int(r_threat_intel or 0))
    if hard >= 85:
        if fused < hard:
            hard_guard_applied = True
        fused = max(fused, hard)
    elif machine.r_machine_final >= 50:
        floor = min(100, round(machine.r_machine_final * 0.85))
        if fused < floor:
            hard_guard_applied = True
        fused = max(fused, floor)

    return RiskFusionResult(
        r_fused=fused,
        r_llm_100=r_llm_100,
        machine=machine,
        hard_guard_applied=hard_guard_applied,
    )


def dominant_source(component_scores: dict[str, int]) -> str:
    if not component_scores:
        return "none"
    ignore = {
        "r_llm_optional",
        "r_llm_100",
        "r_machine_base",
        "r_machine_support_bonus",
        "r_machine_max",
        "r_ueba",
        "delta_user",
        "delta_user_effective",
        "adjusted",
        "semantic_floor",
        "risk_score",
    }
    filtered = {k: v for k, v in component_scores.items() if k not in ignore}
    if not filtered:
        return "none"
    return max(filtered.items(), key=lambda kv: kv[1])[0]


def clamp_delta_user_effective(delta_user: int) -> int:
    """UEBA：正向最多 +15，負向信任最多 -8。"""
    d = int(delta_user or 0)
    if d > 0:
        return min(d, _UEBA_DELTA_POS_CAP)
    if d < 0:
        return max(d, _UEBA_DELTA_NEG_CAP)
    return 0


def apply_ueba_adjustment(
    r_fused: int,
    *,
    delta_user: int,
    r_rules: int,
    r_threat_intel: int,
) -> tuple[int, int, bool]:
    """
    回傳 (adjusted, delta_user_effective, ueba_guard_applied)。
    """
    effective = clamp_delta_user_effective(delta_user)
    adjusted = max(0, min(100, int(r_fused) + effective))
    ueba_guard_applied = False
    floor = max(int(r_rules or 0), int(r_threat_intel or 0))
    if floor >= 85:
        new_val = max(adjusted, floor, int(r_fused))
        ueba_guard_applied = new_val != adjusted
        return new_val, effective, ueba_guard_applied
    if int(r_fused) >= 85:
        new_val = max(adjusted, int(r_fused))
        ueba_guard_applied = new_val != adjusted
        return new_val, effective, ueba_guard_applied
    return adjusted, effective, False


def semantic_floor_from_labels(semantic_labels: list[str] | None) -> int:
    """依 semantic_labels 決定顯示分下限（非強制 verdict）。"""
    floor = 0
    for raw in semantic_labels or []:
        lbl = str(raw).strip().lower().replace("-", "_")
        if not lbl:
            continue
        if lbl in ("financial_extortion", "payment_pressure"):
            floor = max(floor, 85)
        elif lbl == "physical_threat":
            floor = max(floor, 85)
        elif lbl in ("credential_harvesting", "credential_harvest"):
            floor = max(floor, 75)
        elif lbl in ("phishing", "impersonation"):
            floor = max(floor, 60)
        elif lbl == "malicious_link":
            floor = max(floor, 55)
        elif lbl == "urgency_pressure":
            floor = max(floor, 40)
        elif lbl == "suspicious_notification":
            floor = max(floor, 35)
    return floor


def summary_indicates_scam(safety_summary: str) -> bool:
    """語意摘要是否明確指向詐騙（僅供 reason_highlights，不用於顯示分下限）。"""
    s = (safety_summary or "").strip()
    if not s:
        return False
    markers = (
        "詐騙",
        "可疑",
        "恐嚇",
        "勒索",
        "冒充",
        "釣魚",
        "假冒",
        "勿輕信",
        "不要輕信",
        "提高警覺",
        "來源不明",
    )
    return any(m in s for m in markers)


def finalize_display_risk_score(
    r_final: int,
    *,
    delta_user: int,
    r_rules: int,
    r_threat_intel: int,
    r_llm_optional: int = 0,
    safety_summary: str = "",
    semantic_labels: list[str] | None = None,
    apply_semantic_floor: bool = True,
) -> tuple[int, int, int, int, bool]:
    """
    最終顯示分（0–100）。

    回傳 (risk_score, adjusted, delta_user_effective, semantic_floor, ueba_guard_applied)。
    ml_* 模式請設 apply_semantic_floor=False，避免與 ML 雙重抬分。
    """
    _ = safety_summary, r_llm_optional
    adjusted, delta_effective, ueba_guard = apply_ueba_adjustment(
        r_final,
        delta_user=delta_user,
        r_rules=r_rules,
        r_threat_intel=r_threat_intel,
    )
    sem_floor = semantic_floor_from_labels(semantic_labels) if apply_semantic_floor else 0
    risk_score = max(adjusted, sem_floor)
    return risk_score, adjusted, delta_effective, sem_floor, ueba_guard


def recommended_action_label_zh(action: str, risk_score: int) -> str:
    """給手機 UI 的建議動作中文（非內部 continue 代碼）。"""
    a = (action or "").strip().lower()
    if a == "block":
        return "建議阻擋，勿點連結／勿匯款"
    if a == "ask_user":
        return "請提高警覺，建議勿輕信"
    if int(risk_score) >= 40:
        return "目前風險中等，請留意"
    return "分數偏低，仍請留意來路"


def recommended_cai_action(verdict: str, risk_score: int, *, r_rules: int = 0) -> str:
    v = (verdict or "").strip().lower()
    if v == "block" or risk_score >= 85:
        return "block"
    if v == "warn" or risk_score >= 70:
        return "ask_user"
    if int(r_rules) >= 25 or risk_score >= 40:
        return "ask_user"
    return "continue"
