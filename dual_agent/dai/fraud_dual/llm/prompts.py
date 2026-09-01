"""Path B prompt（與 Narrator 分離；不得提及 Result_A 分數）。"""



from __future__ import annotations



import json



from dual_agent.dai.fraud_dual.shared.constants import SCAM_TYPES



PATH_B_SYSTEM = """你是反詐騙研究系統的 Path B 分析器。

任務：依「訊息本文 + 使用者建圖資料 + 共享特徵」獨立評估，輸出單一 JSON 物件。



硬性規則：

1. 只輸出 JSON，不要 Markdown、不要前後說明文字。

2. 欄位必須恰好包含：

   llm_threat (0~1 數字)、llm_scam_type (字串)、llm_context (0~1 數字)、

   llm_channel_familiar (布林)、explanation (繁體中文短句)。

3. llm_scam_type 只能是下列之一：

   {scam_types}

4. llm_threat = 事件本身危險程度（與對象無關的話術／誘導／payload）。

5. llm_context = 對這位使用者的情境風險：

   - 高齡／退休／無投資經驗 + 投資誘導 → llm_context 應偏高（建議 ≥0.7）

   - channel 不在 primary_apps，或 relation=Unknown → 再拉高 llm_context

   - 熟人常用管道 + 無危險 payload 的日常對話 → llm_context 應偏低

   llm_threat 與 llm_context 可不同，禁止合成單一分數。

6. 必須明確判斷 channel 是否屬於 primary_apps，填入 llm_channel_familiar。

7. 不可要求通訊錄或聊天紀錄；不可臆造 ML／GNN／Path A 分數。

""".format(

    scam_types=", ".join(SCAM_TYPES)

)





def build_path_b_user_prompt(

    *,

    text: str,

    build_graph: dict,

    shared_snapshot: dict,

) -> str:

    payload = {

        "message_text": text,

        "build_graph": build_graph,

        "shared_features": shared_snapshot,

        "output_schema_example": {

            "llm_threat": 0.0,

            "llm_scam_type": "Unknown",

            "llm_context": 0.0,

            "llm_channel_familiar": False,

            "explanation": "一句繁中理由",

        },

    }

    return (

        "請分析下列個案並只回傳 JSON：\n"

        + json.dumps(payload, ensure_ascii=False, indent=2)

    )


