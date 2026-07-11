"""DAI 風險評分 ML：特徵抽取、離線重播、模型訓練與推論。"""

from dual_agent.dai.risk_analysis.ml.feature_extractor import RiskFeatureVector, extract_features
from dual_agent.dai.risk_analysis.ml.feature_spec import FEATURE_SPEC_VERSION, all_feature_names
from dual_agent.dai.risk_analysis.ml.gradient_descent_lr import LogisticRegressionGD
from dual_agent.dai.risk_analysis.ml.labels import LabelRecord, load_labels_jsonl, write_labels_jsonl
from dual_agent.dai.risk_analysis.ml.pipeline_replay import replay_feature_context

__all__ = [
    "FEATURE_SPEC_VERSION",
    "LabelRecord",
    "RiskFeatureVector",
    "all_feature_names",
    "extract_features",
    "load_labels_jsonl",
    "LogisticRegressionGD",
    "replay_feature_context",
    "write_labels_jsonl",
]
