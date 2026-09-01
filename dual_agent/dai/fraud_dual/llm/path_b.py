"""Path B：純 LLM 分析（預設 Ollama）。"""



from __future__ import annotations



from typing import Callable



from dual_agent.dai.fraud_dual.llm.input_safe import build_graph_dict, path_b_payload, shared_snapshot

from dual_agent.dai.fraud_dual.llm.ollama import OllamaConfig, OllamaError, chat_json

from dual_agent.dai.fraud_dual.llm.parse import parse_result_b

from dual_agent.dai.fraud_dual.llm.prompts import PATH_B_SYSTEM, build_path_b_user_prompt

from dual_agent.dai.fraud_dual.shared.schemas import BuildGraphInput, ResultB, SharedFeatures



ChatFn = Callable[..., str]





class OllamaPathBAnalyzer:

    """依共享特徵 + 建圖 + 本文獨立產出 Result_B；不接受 Result_A。"""



    def __init__(

        self,

        config: OllamaConfig | None = None,

        *,

        chat_fn: ChatFn | None = None,

    ):

        self.config = config or OllamaConfig.from_env()

        self._chat = chat_fn or chat_json



    def analyze(

        self,

        text: str,

        shared_features: SharedFeatures | dict,

        build_graph: BuildGraphInput | dict,

    ) -> ResultB:

        # 明確拒絕誤傳 Result_A

        if isinstance(shared_features, dict) and (

            "threat_score" in shared_features or "result_a" in shared_features

        ):

            raise ValueError("Path B must not receive Path A scores")



        if isinstance(shared_features, SharedFeatures):

            shared = shared_features

        else:

            raise TypeError("shared_features must be SharedFeatures")



        if isinstance(build_graph, BuildGraphInput):

            build = build_graph

        else:

            build = BuildGraphInput.model_validate(build_graph)



        # 校驗組裝後的輸入（防呆）

        path_b_payload(shared, build)



        user = build_path_b_user_prompt(

            text=text or shared.text,

            build_graph=build_graph_dict(build),

            shared_snapshot=shared_snapshot(shared),

        )

        raw = self._chat(system=PATH_B_SYSTEM, user=user, config=self.config)

        return parse_result_b(raw)





def run_path_b(

    shared: SharedFeatures,

    build: BuildGraphInput,

    *,

    analyzer: OllamaPathBAnalyzer | None = None,

) -> ResultB:

    ana = analyzer or OllamaPathBAnalyzer()

    return ana.analyze(shared.text, shared, build)





__all__ = ["OllamaPathBAnalyzer", "OllamaError", "run_path_b"]


