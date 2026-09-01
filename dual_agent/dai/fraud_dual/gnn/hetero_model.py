"""HeteroGNN：Context Graph → context_score（PyG）。"""

from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn
from torch_geometric.data import HeteroData
from torch_geometric.nn import HeteroConv, Linear, SAGEConv

from dual_agent.dai.fraud_dual.shared.constants import (
    AGE_BANDS,
    CHANNELS,
    OCCUPATIONS,
    RELATION_TYPES,
    SCAM_TYPES,
)

from dual_agent.dai.fraud_dual.paths import HETERO_MODEL_PATH

DEFAULT_HETERO_PATH = HETERO_MODEL_PATH

NODE_TYPES = ("user", "sender", "message", "channel", "intent", "payload")
EDGE_TYPES = (
    ("user", "receives", "message"),
    ("message", "rev_receives", "user"),
    ("sender", "sends", "message"),
    ("message", "rev_sends", "sender"),
    ("message", "via_channel", "channel"),
    ("channel", "rev_via_channel", "message"),
    ("message", "has_intent", "intent"),
    ("intent", "rev_has_intent", "message"),
    ("message", "references", "payload"),
    ("payload", "rev_references", "message"),
)


def _oh(value: str, choices: tuple[str, ...]) -> list[float]:
    return [1.0 if value == c else 0.0 for c in choices]


def _invest(raw) -> float:
    if raw is None or str(raw).strip() == "":
        return 0.5
    s = str(raw).strip().lower()
    if s in {"無", "沒有", "none", "no", "0"}:
        return 0.0
    if s in {"有", "yes", "1", "豐富"}:
        return 1.0
    if s == "普通":
        return 0.6
    return 0.5


def sample_to_hetero(sample) -> HeteroData:
    """ContextSample → HeteroData（單圖）。"""
    data = HeteroData()
    familiar = float(sample.channel_is_familiar)
    data["user"].x = torch.tensor(
        [
            _oh(sample.age_band, AGE_BANDS)
            + _oh(sample.occupation, OCCUPATIONS)
            + [_invest(sample.invest_exp)]
        ],
        dtype=torch.float,
    )
    data["sender"].x = torch.tensor(
        [_oh(sample.relation_type, RELATION_TYPES)],
        dtype=torch.float,
    )
    # message：不餵 threat，避免與 Threat 黏死
    from dual_agent.dai.fraud_dual.shared.features.rhetoric_features import extract_rhetoric_features

    rh = extract_rhetoric_features(sample.text)
    data["message"].x = torch.tensor(
        [
            [
                rh.urgency_score,
                rh.authority_score,
                rh.reward_score,
                rh.fear_score,
                float(rh.obfuscation_flag),
            ]
        ],
        dtype=torch.float,
    )
    data["channel"].x = torch.tensor(
        [_oh(sample.channel, CHANNELS) + [familiar]],
        dtype=torch.float,
    )
    data["intent"].x = torch.tensor(
        [_oh(sample.scam_type, SCAM_TYPES)],
        dtype=torch.float,
    )
    from dual_agent.dai.fraud_dual.shared.features.payload_features import extract_payload_features

    pf = extract_payload_features(sample.text)
    data["payload"].x = torch.tensor(
        [
            [
                pf.payload_risk_score,
                float(pf.contains_url),
                float(pf.url_is_shortener),
                float(pf.contains_apk),
                float(pf.contains_phone),
            ]
        ],
        dtype=torch.float,
    )

    z = torch.tensor([[0], [0]], dtype=torch.long)
    zr = torch.tensor([[0], [0]], dtype=torch.long)
    data["user", "receives", "message"].edge_index = z
    data["message", "rev_receives", "user"].edge_index = zr
    data["sender", "sends", "message"].edge_index = z
    data["message", "rev_sends", "sender"].edge_index = zr
    data["message", "via_channel", "channel"].edge_index = z
    data["channel", "rev_via_channel", "message"].edge_index = zr
    data["message", "has_intent", "intent"].edge_index = z
    data["intent", "rev_has_intent", "message"].edge_index = zr
    data["message", "references", "payload"].edge_index = z
    data["payload", "rev_references", "message"].edge_index = zr
    data.y = torch.tensor([sample.context_score], dtype=torch.float)
    return data


class HeteroContextNet(nn.Module):
    def __init__(self, in_dims: dict[str, int], hidden: int = 64):
        super().__init__()
        self.lin_dict = nn.ModuleDict(
            {nt: Linear(in_dims[nt], hidden) for nt in NODE_TYPES}
        )
        self.conv1 = HeteroConv(
            {et: SAGEConv(hidden, hidden) for et in EDGE_TYPES},
            aggr="sum",
        )
        self.conv2 = HeteroConv(
            {et: SAGEConv(hidden, hidden) for et in EDGE_TYPES},
            aggr="sum",
        )
        self.head = nn.Sequential(
            nn.Linear(hidden, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 1),
            nn.Sigmoid(),
        )

    def forward(self, x_dict, edge_index_dict):
        x_dict = {k: self.lin_dict[k](x).relu() for k, x in x_dict.items()}
        for conv in (self.conv1, self.conv2):
            out = conv(x_dict, edge_index_dict)
            # 保留未被更新的節點型別
            x_dict = {k: out[k].relu() if k in out else x_dict[k] for k in x_dict}
        return self.head(x_dict["message"]).view(-1)


def infer_in_dims() -> dict[str, int]:
    return {
        "user": len(AGE_BANDS) + len(OCCUPATIONS) + 1,
        "sender": len(RELATION_TYPES),
        "message": 5,
        "channel": len(CHANNELS) + 1,
        "intent": len(SCAM_TYPES),
        "payload": 5,
    }
