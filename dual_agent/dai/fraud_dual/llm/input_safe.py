"""組裝 Path B 輸入：只含共享特徵／建圖／本文，嚴禁 Path A 分數。"""



from __future__ import annotations



from typing import Any



from dual_agent.dai.fraud_dual.shared.schemas import BuildGraphInput, SharedFeatures



# Path B 禁止出現的鍵（防呆：輸入 JSON 不得外洩 A 路分數）

_FORBIDDEN_KEYS = frozenset(

    {

        "threat_score",

        "context_score",

        "scam_type",

        "intent_confidence",

        "threat_missing",

        "result_a",

        "threat",

        "graph_writeback",

    }

)





def assert_no_path_a_scores(obj: Any, *, path: str = "$") -> None:

    if isinstance(obj, dict):

        for k, v in obj.items():

            if k in _FORBIDDEN_KEYS:

                raise ValueError(f"Path B input must not contain Path A field: {path}.{k}")

            assert_no_path_a_scores(v, path=f"{path}.{k}")

    elif isinstance(obj, list):

        for i, item in enumerate(obj):

            assert_no_path_a_scores(item, path=f"{path}[{i}]")





def build_graph_dict(build: BuildGraphInput) -> dict:

    return {

        "age_band": build.age_band,

        "occupation": build.occupation,

        "relation_type": build.relation_type,

        "channel": build.channel,

        "primary_apps": list(build.primary_apps),

        "invest_exp": build.invest_exp,

    }





def shared_snapshot(shared: SharedFeatures) -> dict:

    """結構化特徵快照（不含 Path A 輸出）。"""

    ch = shared.channel_features

    return {

        "message_features": shared.message_features.model_dump(),

        "intent_features": shared.intent_features.model_dump(),

        "payload_features": shared.payload_features.model_dump(),

        "channel_features": {

            "channel": ch.channel,

            "primary_apps": list(ch.primary_apps),

            "channel_is_familiar": bool(ch.channel_is_familiar),

            "channel_risk_score": ch.channel_risk_score,

        },

        "user_context": dict(shared.user_context),

    }





def path_b_payload(shared: SharedFeatures, build: BuildGraphInput) -> dict:

    payload = {

        "text": shared.text,

        "build_graph": build_graph_dict(build),

        "shared_features": shared_snapshot(shared),

    }

    assert_no_path_a_scores(payload)

    return payload


