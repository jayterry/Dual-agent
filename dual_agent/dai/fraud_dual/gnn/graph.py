"""Context Graph 建圖（對齊 GNN.md / 節點說明.md）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from dual_agent.dai.fraud_dual.shared.schemas import GraphWriteback, SharedFeatures


@dataclass
class ContextGraph:
    """異質小圖：節點屬性 + 有向邊清單（無 HAS_RELATION）。"""

    nodes: dict[str, dict] = field(default_factory=dict)
    edges: list[dict[str, str]] = field(default_factory=list)

    def add_node(self, node_id: str, ntype: str, **attrs) -> None:
        self.nodes[node_id] = {"type": ntype, **attrs}

    def add_edge(self, src: str, rel: str, dst: str) -> None:
        self.edges.append({"src": src, "rel": rel, "dst": dst})

    def to_payload(self) -> dict:
        return {
            "nodes": self.nodes,
            "edges": self.edges,
            "signals": self.extract_signals(),
        }

    def extract_signals(self) -> dict:
        """規則／GNN 共用的扁平訊號（便於單元測試）。"""
        user = self.nodes.get("user", {})
        sender = self.nodes.get("sender", {})
        msg = self.nodes.get("message", {})
        channel = self.nodes.get("channel", {})
        intent = self.nodes.get("intent", {})
        payloads = [
            n for nid, n in self.nodes.items() if n.get("type") == "Payload"
        ]
        return {
            "age_band": user.get("age_band"),
            "occupation": user.get("occupation"),
            "invest_exp": user.get("invest_exp"),
            "primary_apps": user.get("primary_apps", []),
            "relation_type": sender.get("relation_type"),
            "channel": channel.get("name"),
            "channel_is_familiar": channel.get("channel_is_familiar", 0),
            "scam_type": intent.get("scam_type") or msg.get("scam_type"),
            "threat_score": msg.get("threat_score", 0.0),
            "threat_missing": msg.get("threat_missing", 0),
            "urgency_score": msg.get("urgency_score", 0.0),
            "authority_score": msg.get("authority_score", 0.0),
            "reward_score": msg.get("reward_score", 0.0),
            "fear_score": msg.get("fear_score", 0.0),
            "payload_risk_score": max(
                (p.get("payload_risk_score", 0.0) for p in payloads),
                default=0.0,
            ),
            "has_payload": int(bool(payloads)),
            "payload_types": [p.get("payload_type") for p in payloads],
        }


def build_context_graph(
    shared: SharedFeatures,
    writeback: GraphWriteback,
) -> ContextGraph:
    """由共享特徵 + ML 回寫組出 Context Graph。"""
    g = ContextGraph()
    uc = shared.user_context
    cf = shared.channel_features
    pf = shared.payload_features

    g.add_node(
        "user",
        "User",
        age_band=uc.get("age_band"),
        occupation=uc.get("occupation"),
        primary_apps=list(cf.primary_apps),
        invest_exp=uc.get("invest_exp"),
    )
    g.add_node(
        "sender",
        "Sender",
        relation_type=uc.get("relation_type"),
    )
    g.add_node("message", "Message", **writeback.message)
    g.add_node(
        "channel",
        "Channel",
        name=cf.channel,
        channel_is_familiar=cf.channel_is_familiar,
        channel_risk_score=cf.channel_risk_score,
    )
    g.add_node("intent", "Intent", scam_type=writeback.intent)

    g.add_edge("user", "RECEIVES", "message")
    g.add_edge("sender", "SENDS", "message")
    g.add_edge("message", "VIA_CHANNEL", "channel")
    g.add_edge("message", "HAS_INTENT", "intent")

    # Payload：有實體才建節點與 REFERENCES
    for i, ptype in enumerate(writeback.payload_types):
        nid = f"payload_{i}"
        g.add_node(
            nid,
            "Payload",
            payload_type=ptype,
            payload_risk_score=pf.payload_risk_score,
            contains_url=pf.contains_url,
            url_is_shortener=pf.url_is_shortener,
            contains_apk=pf.contains_apk,
            contains_phone=pf.contains_phone,
            contains_account=pf.contains_account,
        )
        g.add_edge("message", "REFERENCES", nid)

    return g


def graph_as_dict(graph: ContextGraph) -> dict:
    return asdict(graph)
