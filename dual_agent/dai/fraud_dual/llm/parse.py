"""將 LLM 字串解析／正規化為 ResultB。"""



from __future__ import annotations



import json

import re

from typing import Any



from dual_agent.dai.fraud_dual.shared.constants import SCAM_TYPES

from dual_agent.dai.fraud_dual.shared.schemas import ResultB





def extract_json_object(text: str) -> dict[str, Any]:

    text = text.strip()

    if text.startswith("```"):

        text = re.sub(r"^```(?:json)?\s*", "", text)

        text = re.sub(r"\s*```$", "", text)

    try:

        obj = json.loads(text)

        if isinstance(obj, dict):

            return obj

    except json.JSONDecodeError:

        pass

    m = re.search(r"\{.*\}", text, flags=re.DOTALL)

    if not m:

        raise ValueError(f"No JSON object in LLM output: {text[:300]}")

    obj = json.loads(m.group(0))

    if not isinstance(obj, dict):

        raise ValueError("LLM JSON root must be object")

    return obj





def _clip01(v: Any, name: str) -> float:

    try:

        x = float(v)

    except (TypeError, ValueError) as e:

        raise ValueError(f"{name} must be number, got {v!r}") from e

    return max(0.0, min(1.0, x))





def _scam_type(raw: Any) -> str:

    s = str(raw).strip()

    if s in SCAM_TYPES:

        return s

    # 容錯常見變體

    aliases = {

        "investment": "Investment",

        "loan": "Loan",

        "romance": "Romance",

        "fake_cs": "Fake_CS",

        "fake cs": "Fake_CS",

        "otp": "OTP_Scam",

        "otp_scam": "OTP_Scam",

        "job": "Job_Scam",

        "job_scam": "Job_Scam",

        "gov_subsidy": "Gov_Subsidy",

        "impersonation_authority": "Impersonation_Authority",

        "parcel": "Parcel",

        "account_freeze": "Account_Freeze",

        "unknown": "Unknown",

    }

    return aliases.get(s.lower(), "Unknown")





def _bool(v: Any) -> bool:

    if isinstance(v, bool):

        return v

    if isinstance(v, (int, float)):

        return bool(v)

    s = str(v).strip().lower()

    if s in {"1", "true", "yes", "y", "是"}:

        return True

    if s in {"0", "false", "no", "n", "否"}:

        return False

    raise ValueError(f"llm_channel_familiar must be bool, got {v!r}")





def parse_result_b(raw_text: str) -> ResultB:

    obj = extract_json_object(raw_text)

    return ResultB(

        llm_threat=round(_clip01(obj.get("llm_threat"), "llm_threat"), 4),

        llm_scam_type=_scam_type(obj.get("llm_scam_type", "Unknown")),  # type: ignore[arg-type]

        llm_context=round(_clip01(obj.get("llm_context"), "llm_context"), 4),

        llm_channel_familiar=_bool(obj.get("llm_channel_familiar", False)),

        explanation=str(obj.get("explanation") or "").strip() or "（無說明）",

    )


