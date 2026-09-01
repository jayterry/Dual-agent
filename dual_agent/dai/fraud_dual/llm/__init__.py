"""LLM 模組：Path B（對照）與 Narrator（可選解釋）。"""



from __future__ import annotations



from typing import Protocol



from dual_agent.dai.fraud_dual.llm.ollama import OllamaConfig, OllamaError

from dual_agent.dai.fraud_dual.llm.path_b import OllamaPathBAnalyzer, run_path_b

from dual_agent.dai.fraud_dual.shared.schemas import ResultA, ResultB



__all__ = [

    "PathBAnalyzer",

    "Narrator",

    "OllamaPathBAnalyzer",

    "OllamaConfig",

    "OllamaError",

    "run_path_b",

    "not_implemented_narrator",

]





class PathBAnalyzer(Protocol):

    """純 LLM；不得讀取 Result_A 分數。"""



    def analyze(

        self,

        text: str,

        shared_features: object,

        build_graph: object,

    ) -> ResultB:

        ...





class Narrator(Protocol):

    """只解釋 Result_A，不得改分數。"""



    def narrate(self, result_a: ResultA, graph_summary: dict) -> str:

        ...





def not_implemented_narrator(*_args, **_kwargs) -> str:

    raise NotImplementedError("Narrator will be implemented later")


