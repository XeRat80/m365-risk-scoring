from __future__ import annotations

import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pytest
from skl2onnx import to_onnx
from sklearn.linear_model import LogisticRegression

from packages.ml.m365risk_ml.features import FEATURE_NAMES
from packages.ml.m365risk_ml.runtime import ModelRuntime
from packages.ml.m365risk_ml.scoring import HYBRID_WEIGHTS
from scripts.build_demo_model import build


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_bundle(root: Path, approved: bool = False) -> None:
    root.mkdir()
    x = np.vstack([np.zeros(len(FEATURE_NAMES)), np.ones(len(FEATURE_NAMES))]).astype(np.float32)
    model = LogisticRegression().fit(x, np.asarray([0, 1]))
    joblib.dump(model, root / "pipeline.joblib")
    (root / "model.onnx").write_bytes(
        to_onnx(model, x[:1], target_opset=18).SerializeToString()
    )
    (root / "feature_schema.json").write_text(
        json.dumps({"version": "EmailMetadataV1", "features": FEATURE_NAMES})
    )
    (root / "hybrid_weights.json").write_text(json.dumps(HYBRID_WEIGHTS))
    (root / "thresholds.json").write_text(json.dumps({"email_probability": 0.5}))
    artifacts = {
        name: digest(root / name)
        for name in (
            "pipeline.joblib",
            "model.onnx",
            "feature_schema.json",
            "hybrid_weights.json",
            "thresholds.json",
        )
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": "unit-model",
                "status": "approved" if approved else "demo",
                "approved": approved,
                "artifacts": artifacts,
            }
        )
    )


def test_runtime_verifies_bundle_and_scores_in_schema_order(tmp_path: Path) -> None:
    root = tmp_path / "model"
    model_bundle(root)
    runtime = ModelRuntime.load(root)
    probability = runtime.predict({name: 1.0 for name in reversed(FEATURE_NAMES)}, {})
    assert probability > 0.5
    assert runtime.onnx_session is not None
    assert runtime.version == "unit-model"
    assert runtime.approved is False
    with pytest.raises(RuntimeError, match="approved model"):
        ModelRuntime.load(root, require_approved=True)


def test_runtime_rejects_tampered_or_drifted_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "model"
    model_bundle(root, approved=True)
    (root / "thresholds.json").write_text('{"email_probability": 0.9}')
    with pytest.raises(RuntimeError, match="integrity"):
        ModelRuntime.load(root, require_approved=True)
    model_bundle(tmp_path / "drifted", approved=True)
    schema = tmp_path / "drifted" / "feature_schema.json"
    schema.write_text(json.dumps({"features": FEATURE_NAMES[:-1]}))
    manifest = json.loads((tmp_path / "drifted" / "manifest.json").read_text())
    manifest["artifacts"]["feature_schema.json"] = digest(schema)
    (tmp_path / "drifted" / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(RuntimeError, match="feature schema"):
        ModelRuntime.load(tmp_path / "drifted", require_approved=True)


def test_explicit_rules_demo_bundle_runs_without_training_data(tmp_path: Path) -> None:
    root = tmp_path / "rules-demo"
    manifest = build(root)
    runtime = ModelRuntime.load(root)
    probability = runtime.predict(
        {name: 0.0 for name in FEATURE_NAMES},
        {
            "authenticationResults": {"spf": "fail", "dkim": "fail", "dmarc": "fail"},
            "replyToDomainMismatch": True,
        },
    )
    assert manifest["status"] == "demo"
    assert runtime.pipeline is None
    assert probability > 0.5
    with pytest.raises(RuntimeError, match="approved model"):
        ModelRuntime.load(root, require_approved=True)
