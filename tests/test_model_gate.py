from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.check_model_gate import assess_bundle


def _write_bundle(root: Path, *, declared_approved: bool = True) -> Path:
    artifact = root / "pipeline.joblib"
    artifact.write_bytes(b"model")
    manifest = {
        "version": "1.0.0",
        "approved": declared_approved,
        "status": "approved" if declared_approved else "demo",
        "selected_model": "logistic",
        "metrics": {
            "selected": {
                "pr_auc": 0.94,
                "precision": 0.90,
                "recall": 0.84,
                "brier": 0.08,
                "ece": 0.03,
            },
            "email_models": [{"name": "rules", "pr_auc": 0.80}],
            "user_risk": {
                "top_10_recall": 0.85,
                "false_alerts_per_100": 4.0,
                "median_detection_delay_days": 1.0,
            },
            "onnx_max_abs_difference": 1e-7,
        },
        "artifacts": {"pipeline.joblib": hashlib.sha256(b"model").hexdigest()},
    }
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_model_gate_recomputes_metrics_and_hashes(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    assert assess_bundle(manifest) == (True, [])

    payload = json.loads(manifest.read_text())
    payload["metrics"]["selected"]["ece"] = 0.2
    manifest.write_text(json.dumps(payload))
    approved, failures = assess_bundle(manifest)
    assert approved is False
    assert any("ECE" in failure for failure in failures)
    assert any("approval state" in failure for failure in failures)


def test_model_gate_rejects_tampered_artifact(tmp_path: Path) -> None:
    manifest = _write_bundle(tmp_path)
    (tmp_path / "pipeline.joblib").write_bytes(b"tampered")
    approved, failures = assess_bundle(manifest)
    assert approved is False
    assert any("checksum differs" in failure for failure in failures)
