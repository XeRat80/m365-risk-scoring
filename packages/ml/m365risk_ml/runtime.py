from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from onnxruntime import InferenceSession

from .features import FEATURE_NAMES
from .scoring import HYBRID_WEIGHTS, email_threat_score, precision_guarded_email_probability


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ModelRuntime:
    version: str
    status: str
    approved: bool
    pipeline: object | None
    onnx_session: InferenceSession | None
    weights: dict[str, float]
    thresholds: dict[str, float]

    @classmethod
    def load(cls, root: Path, *, require_approved: bool = False) -> ModelRuntime:
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            if require_approved:
                raise RuntimeError("Production requires an approved model manifest")
            return cls("rules-demo", "demo", False, None, None, dict(HYBRID_WEIGHTS), {})
        manifest = json.loads(manifest_path.read_text())
        if require_approved and not manifest.get("approved"):
            raise RuntimeError("Production requires an approved model bundle")
        schema = json.loads((root / "feature_schema.json").read_text())
        if schema.get("features") != FEATURE_NAMES:
            raise RuntimeError("Model feature schema does not match the runtime contract")
        for name, expected in manifest.get("artifacts", {}).items():
            path = root / name
            if not path.exists() or _sha256(path) != expected:
                raise RuntimeError(f"Model artifact integrity check failed: {name}")
        weights = {key: float(value) for key, value in json.loads((root / "hybrid_weights.json").read_text()).items()}
        if set(weights) != set(HYBRID_WEIGHTS) or any(value < 0 for value in weights.values()):
            raise RuntimeError("Hybrid weights are invalid")
        if not np.isclose(sum(weights.values()), 1.0, atol=1e-6):
            raise RuntimeError("Hybrid weights must sum to one")
        thresholds = {
            key: float(value)
            for key, value in json.loads((root / "thresholds.json").read_text()).items()
        }
        selected_model = str(manifest.get("selected_model", ""))
        pipeline_path = root / "pipeline.joblib"
        if selected_model == "rules":
            if manifest.get("approved"):
                raise RuntimeError("A rules-only demo bundle cannot be production-approved")
            pipeline = None
            onnx_session = None
        else:
            onnx_path = root / "model.onnx"
            if not pipeline_path.exists() and not onnx_path.exists():
                raise RuntimeError("Model pipeline or ONNX artifact is missing")
            pipeline = joblib.load(pipeline_path) if pipeline_path.exists() else None
            onnx_session = (
                InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
                if onnx_path.exists()
                else None
            )
        return cls(
            version=str(manifest["version"]),
            status=str(manifest["status"]),
            approved=bool(manifest["approved"]),
            pipeline=pipeline,
            onnx_session=onnx_session,
            weights=weights,
            thresholds=thresholds,
        )

    def predict(
        self, features: Mapping[str, float], fallback_message: Mapping[str, object]
    ) -> float:
        if self.pipeline is None and self.onnx_session is None:
            probability = email_threat_score(fallback_message)[0]
            return precision_guarded_email_probability(probability, fallback_message)
        ordered = np.asarray([[float(features[name]) for name in FEATURE_NAMES]], dtype=np.float32)
        if self.onnx_session is not None:
            input_name = self.onnx_session.get_inputs()[0].name
            output = self.onnx_session.run(None, {input_name: ordered})[-1]
            if isinstance(output, list):
                row = output[0]
                probability = float(row[1] if isinstance(row, dict) else row[1])
            else:
                probability = float(np.asarray(output)[0, 1])
        else:
            assert self.pipeline is not None
            probability = self.pipeline.predict_proba(ordered)[0, 1]  # type: ignore[attr-defined]
        return precision_guarded_email_probability(float(probability), fallback_message)
