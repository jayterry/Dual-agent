"""模擬語料測試。"""

from __future__ import annotations

from dual_agent.dai.risk_analysis.ml.synthetic_corpus import BENIGN_TEMPLATES, SCAM_TEMPLATES


def test_synthetic_corpus_size() -> None:
    assert len(SCAM_TEMPLATES) >= 80
    assert len(BENIGN_TEMPLATES) >= 50
    assert len(SCAM_TEMPLATES) + len(BENIGN_TEMPLATES) >= 130


def test_bootstrap_stratified_split() -> None:
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "bootstrap_synthetic_labels",
        root / "scripts" / "bootstrap_synthetic_labels.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    records = mod.build_synthetic_records(seed=42)
    assert len(records) == len(SCAM_TEMPLATES) + len(BENIGN_TEMPLATES)
    for label in ("scam", "benign"):
        subset = [r for r in records if r.label == label]
        splits = {r.split for r in subset}
        assert "train" in splits
        assert len(subset) >= 10
