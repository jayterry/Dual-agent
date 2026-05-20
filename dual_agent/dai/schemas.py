"""DAI 精簡版：Defense LLM + Defense Execute 資料結構（不與 CAI 耦合）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RecommendedCAIAction = Literal["continue", "ask_user", "block", "narrow_tools"]


@dataclass
class DAIRequest:
    """呼叫 DAI 防禦管線的輸入（日後 call_dai 可對齊此型別）。"""

    user_text: str
    context_pack: str = ""
    """可選：長脈絡／摘要（與 CAI Context Pack 對齊用字串即可）。"""
    artifact: str = ""
    """可選：待審內容（簡訊全文、fetch_url 摘要、工具輸出等）。"""
    sms_review: bool = False
    """若 True：走 risk_analysis 管線（機器分項 + 語意補充），不再用 Defense 計畫 LLM 主評分。"""
    sender_display: str = ""
    sender_number: str = ""
    sender_tech_context: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    """UEBA 來源標籤（如 sms_share、desktop）。"""


@dataclass
class DefenseStep:
    """Defense LLM 產生的內部子步驟（由 defense_execute 執行）。"""

    skill: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class DefenseReplanOutput:
    """
    Defense LLM **單次**輸出（對齊 CAI Replan：依 observation 決定再派一步或結束）。
    - complete=false：必須提供 **恰好一個** next_defense_step，由 Execute 執行後進入下一輪 LLM。
    - complete=true：next_defense_step 應為 None，並填寫最終 risk／摘要等欄位。
    """

    complete: bool
    next_defense_step: DefenseStep | None
    risk_score: int
    risk_labels: list[str]
    safety_summary: str
    evidence: list[dict[str, Any]]
    tool_restrictions: dict[str, Any]
    recommended_cai_action: RecommendedCAIAction
    raw_message: str = ""


@dataclass
class DefensePlan:
    """舊版「一次多個 defense_todos」計畫；僅供測試或向後相容，正常管線請用 DefenseReplanOutput 迴圈。"""

    risk_score: int
    risk_labels: list[str]
    safety_summary: str
    evidence: list[dict[str, Any]]
    tool_restrictions: dict[str, Any]
    recommended_cai_action: RecommendedCAIAction
    defense_todos: list[DefenseStep] = field(default_factory=list)
    raw_message: str = ""


@dataclass
class DefenseObservation:
    """單一步驟執行紀錄。"""

    skill: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class DAIResult:
    """防禦管線最終輸出（日後作為 CAI observation 內容）。"""

    ok: bool
    risk_score: int
    risk_labels: list[str]
    safety_summary: str
    evidence: list[dict[str, Any]]
    tool_restrictions: dict[str, Any]
    recommended_cai_action: RecommendedCAIAction
    defense_observations: list[DefenseObservation] = field(default_factory=list)
    defense_llm_turns: int = 0
    """本輪 Defense LLM 呼叫次數（含最後一次 complete）。"""
    error: str | None = None
