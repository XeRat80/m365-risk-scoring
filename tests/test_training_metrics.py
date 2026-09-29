from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier

from packages.ml.m365risk_ml import train as training
from packages.ml.m365risk_ml.features import FEATURE_NAMES, chronological_split
from packages.ml.m365risk_ml.train import (
    _feature_importance,
    evaluate,
    expected_calibration_error,
    rules_probability,
    threshold_for_gate,
    user_risk_metrics,
)


def test_metric_helpers_are_deterministic() -> None:
    labels = np.asarray([0, 0, 1, 1])
    probabilities = np.asarray([0.05, 0.25, 0.8, 0.95])
    assert expected_calibration_error(labels, probabilities, bins=2) >= 0
    threshold, precision, recall = threshold_for_gate(labels, probabilities)
    assert 0 <= threshold <= 1
    assert precision == 1
    assert recall == 1
    metrics = evaluate("candidate", labels, probabilities)
    assert metrics["pr_auc"] == 1
    assert metrics["tp"] == 2


def test_rule_baseline_and_grouped_split() -> None:
    frame = pd.DataFrame(
        {
            "archive": ["a", "a", "a", "b", "b"],
            "missing_message_id": [0, 1, 0, 0, 1],
            "reply_to_mismatch": [0, 0, 1, 0, 1],
            "return_path_mismatch": [0, 0, 0, 1, 0],
            "has_html_content_type": [0, 1, 0, 1, 0],
            "encoded_from": [0, 0, 0, 0, 1],
            "received_hops": [2, 9, 3, 4, 12],
            "has_list_id": [0, 0, 1, 0, 0],
        }
    )
    probability = rules_probability(frame)
    assert np.all((probability >= 0) & (probability <= 1))
    train, test = chronological_split(frame, test_fraction=0.4)
    assert set(train).isdisjoint(test)
    assert set(train) | set(test) == set(frame.index)


def test_training_exports_complete_demo_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rng = np.random.default_rng(365)
    rows = 240
    frame = pd.DataFrame({name: rng.integers(0, 3, rows).astype(float) for name in FEATURE_NAMES})
    frame["archive"] = np.repeat(["ham-a", "spam-a", "ham-b", "spam-b"], rows // 4)
    frame["label"] = np.repeat([0, 1, 0, 1], rows // 4)
    frame["sequence"] = np.tile(np.arange(rows // 4), 4)
    frame["message_key"] = [f"message-{index}" for index in range(rows)]
    monkeypatch.setattr(training, "load_spamassassin", lambda _: frame)
    monkeypatch.setattr(
        training,
        "tune_hybrid_weights",
        lambda _: (
            dict(training.HYBRID_WEIGHTS),
            {
                "top_10_recall": 1.0,
                "false_alerts_per_100": 0.0,
                "median_detection_delay_days": 0.0,
            },
            {"promoted": False, "reason": "unit test", "baseline": {}},
        ),
    )
    monkeypatch.setattr(
        training,
        "fit_enron_baseline",
        lambda _: {"version": "UserDailyFeaturesV1", "fit_rows": 10},
    )
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "DATASET_MANIFEST.json").write_text("{}\n")
    (tmp_path / "synthetic" / "m365_user_daily.csv.gz").write_bytes(b"fixture")
    output = tmp_path / "model"
    manifest = training.train(tmp_path, output)
    assert manifest["status"] in {"approved", "demo"}
    assert manifest["selected_model"] in {
        "logistic",
        "random_forest",
        "extra_trees",
        "gradient_boosting",
    }
    for filename in (
        "pipeline.joblib",
        "model.onnx",
        "feature_schema.json",
        "availability_schema_v2.json",
        "metrics.json",
        "manifest.json",
        "model_card.md",
        "behavior_baseline.json",
    ):
        assert (output / filename).is_file()


def test_user_metrics_do_not_treat_missing_sources_as_safe(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "tenant_id": ["tenant", "tenant"],
            "user_id": ["covered", "missing"],
            "date": ["2026-01-01", "2026-01-01"],
            "email_risk_max": [0.8, np.nan],
            "behaviour_anomaly_score": [0.7, np.nan],
            "entra_risk_level": ["high", "unknown"],
            "is_mfa_registered": ["false", "unknown"],
            "is_admin": ["true", "unknown"],
            "label": [1, 0],
        }
    )
    metrics = user_risk_metrics(tmp_path / "unused.csv.gz", frame=frame)
    assert metrics["scored_rows"] == 1
    assert metrics["insufficient_data_rows"] == 1


def test_tree_bundle_exports_real_feature_importance() -> None:
    model = RandomForestClassifier(n_estimators=10, random_state=365).fit(
        np.asarray(
            [[0.0, 0.0], [0.0, 1.0], [0.1, 0.0], [0.1, 1.0],
             [0.9, 0.0], [0.9, 1.0], [1.0, 0.0], [1.0, 1.0]],
            dtype=np.float32,
        ),
        np.asarray([0, 0, 0, 0, 1, 1, 1, 1]),
    )
    importance = _feature_importance(model, "random_forest")
    assert len(importance) == 2
    assert importance.sum() == pytest.approx(1.0)
