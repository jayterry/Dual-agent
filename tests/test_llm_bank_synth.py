"""銀行面合成語料與特徵回填測試。"""

from __future__ import annotations

import json

from dual_agent.dai.risk_analysis.ml.feature_extractor import extract_features
from dual_agent.dai.risk_analysis.ml.feature_spec import all_feature_names
from dual_agent.dai.risk_analysis.ml.llm_synth import (
    BANK_BENIGN_BUCKETS,
    BANK_SCAM_BUCKETS,
    expand_bank_templates,
    generate_bank_corpus,
    invoke_llm_batch,
)
from dual_agent.dai.risk_analysis.rules import score_r_rules


def test_expand_bank_templates_counts() -> None:
    items = expand_bank_templates(n_scam=30, n_benign=30, seed=1)
    assert sum(1 for x in items if x.label == "scam") == 30
    assert sum(1 for x in items if x.label == "benign") == 30
    assert all(x.bucket.startswith("bank_") for x in items)
    texts = [x.text for x in items]
    assert len(texts) == len(set(texts))


def test_generate_bank_corpus_fallback_600() -> None:
    recs = generate_bank_corpus(n_scam=300, n_benign=300, use_llm=False, seed=42)
    assert len(recs) == 600
    assert sum(1 for r in recs if r.label == "scam") == 300
    assert sum(1 for r in recs if r.label == "benign") == 300
    assert all(r.notes.startswith("bank_") for r in recs)
    assert {r.split for r in recs} <= {"train", "val", "test"}


def test_invoke_llm_batch_with_stub() -> None:
    payload = {
        "items": [
            {"text": "【玉山銀行】請回傳網銀驗證碼完成解鎖作業立刻", "fraud_types": ["credential_harvesting"]},
            {"text": "【中信】帳戶異常請提供動態密碼給客服專員處理", "fraud_types": ["credential_harvesting"]},
        ]
    }

    def fake(_user: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    rows = invoke_llm_batch(
        bucket="bank_otp",
        meta=BANK_SCAM_BUCKETS["bank_otp"],
        n=2,
        model="stub",
        base_url="http://localhost",
        invoke_fn=fake,
    )
    assert len(rows) == 2
    assert "驗證碼" in rows[0]["text"] or "動態密碼" in rows[1]["text"]


def test_generate_with_stub_llm_then_fill() -> None:
    def fake(_user: str) -> str:
        return json.dumps(
            {
                "items": [
                    {
                        "text": "【測試銀行】請立刻回傳網銀密碼以解除凍結狀態ABC",
                        "fraud_types": ["credential_harvesting"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    recs = generate_bank_corpus(
        n_scam=12,
        n_benign=12,
        use_llm=True,
        seed=3,
        batch_size=4,
        invoke_fn=fake,
    )
    assert len(recs) == 24
    assert sum(1 for r in recs if r.label == "scam") == 12


def test_feature_url_amount_fallback() -> None:
    text = "請打開 https://www.ctbcbank.com 查匯率，入帳 NT$1,200"
    rules = score_r_rules(text)
    fv = extract_features(
        text=text,
        component_scores={
            "r_rules": rules.score,
            "r_threat_intel": 0,
            "r_tls": 0,
            "r_toxic_fused": 0,
            "tier_h": 0,
            "tier_i": 0,
            "r_llm_optional": 0,
        },
        rules_hits=[],
        urls=None,
        amounts=None,
        phones=None,
    )
    d = fv.to_dict()
    assert d["url_count"] >= 1.0
    assert d["amount_count"] >= 1.0
    assert d["has_https"] == 1.0
    assert len(fv.values) == len(all_feature_names())


def test_bucket_keys_stable() -> None:
    assert set(BANK_SCAM_BUCKETS) == {
        "bank_otp",
        "bank_password",
        "bank_card",
        "bank_phish_url",
        "bank_transfer",
        "bank_loan",
    }
    assert set(BANK_BENIGN_BUCKETS) == {
        "bank_official_notify",
        "bank_app_alert",
        "bank_work_assign",
    }
