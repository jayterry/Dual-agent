"""規則基線 Context Scorer（計劃書 §8.4；與 Threat 不融合）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from dual_agent.dai.fraud_dual.gnn.graph import ContextGraph


@dataclass
class ContextPrediction:
    context_score: float
    factors: list[str] = field(default_factory=list)
    backend: str = "rules_v1"


class RuleContextScorer:
    """
    可解釋加權規則：只回答「對這位使用者是否危險／不合理」。
    不做 threat_score 加權融合。
    """

    def predict_context(self, graph_payload: dict) -> float:
        return self.predict(graph_payload).context_score

    def predict(
        self,
        graph_or_payload: ContextGraph | dict,
    ) -> ContextPrediction:
        if isinstance(graph_or_payload, ContextGraph):
            sig = graph_or_payload.extract_signals()
        else:
            sig = graph_or_payload.get("signals") or graph_or_payload

        score = 0.0
        factors: list[str] = []

        familiar = int(sig.get("channel_is_familiar") or 0)
        relation = sig.get("relation_type") or "Unknown"
        scam_type = sig.get("scam_type") or "Unknown"
        age = sig.get("age_band") or "25-39"
        occupation = sig.get("occupation") or "other"
        reward = float(sig.get("reward_score") or 0.0)
        urgency = float(sig.get("urgency_score") or 0.0)
        fear = float(sig.get("fear_score") or 0.0)
        payload_risk = float(sig.get("payload_risk_score") or 0.0)
        invest_exp = sig.get("invest_exp")

        # 1) 非常用管道
        if familiar == 0:
            score += 0.28
            factors.append("unfamiliar_channel")

        # 2) Unknown 關係 + 高誘因／投資類 intent
        if relation == "Unknown":
            score += 0.12
            factors.append("unknown_relation")
            if reward >= 0.45 or scam_type in {
                "Investment",
                "Loan",
                "Job_Scam",
                "Romance",
            }:
                score += 0.18
                factors.append("unknown_sender_high_inducement")

        # 3) 自稱官方但模型判斷假客服
        if relation == "Official" and scam_type == "Fake_CS":
            score += 0.25
            factors.append("official_claim_vs_fake_cs")

        # 4) 高齡 + payload／高風險 intent
        if age == "60+":
            score += 0.10
            factors.append("elder_age")
            if payload_risk >= 0.35:
                score += 0.22 * payload_risk
                factors.append("elder_high_payload")
            if scam_type in {"Investment", "Loan", "OTP_Scam", "Fake_CS"}:
                score += 0.12
                factors.append("elder_scam_intent")

        # 5) 退休 + 投資誘導
        if occupation == "retired" and scam_type == "Investment":
            score += 0.10
            factors.append("retired_investment")

        # 6) 學生 + 貸款／打工類
        if occupation == "student" and scam_type in {"Loan", "Job_Scam"}:
            score += 0.08
            factors.append("student_loan_or_job")

        # 7) 無投資經驗（若有填）撞上 Investment
        if (
            invest_exp is not None
            and str(invest_exp).strip().lower() in {"", "none", "no", "0", "無", "沒有"}
            and scam_type == "Investment"
        ):
            score += 0.08
            factors.append("no_invest_exp")

        # 8) Payload 本身增加「對此人可執行風險面」
        if payload_risk > 0:
            score += 0.20 * payload_risk
            factors.append("payload_surface")

        # 9) 陌生／偽官方 + 急迫／恐嚇
        if relation in {"Unknown", "Official"} and (urgency >= 0.5 or fear >= 0.5):
            score += 0.06 * max(urgency, fear)
            factors.append("pressure_from_untrusted_sender")

        # 10) 熟人管道且親友關係：略降（仍可能被冒用，但不歸零）
        if familiar == 1 and relation in {"Family", "Friend", "Colleague"}:
            if scam_type == "Unknown" and payload_risk < 0.2 and reward < 0.3:
                score = max(0.0, score - 0.12)
                factors.append("familiar_trusted_soft_discount")

        score = round(max(0.0, min(1.0, score)), 4)
        return ContextPrediction(
            context_score=score,
            factors=factors,
            backend="rules_v1",
        )
