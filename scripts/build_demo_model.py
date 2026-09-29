#!/usr/bin/env python3
"""Create the explicit metadata-rules bundle used by a fresh offline demo."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from packages.ml.m365risk_ml.features import FEATURE_NAMES
from packages.ml.m365risk_ml.scoring import HYBRID_WEIGHTS


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, str] = {
        "feature_schema.json": json.dumps(
            {"version": "EmailMetadataV1", "features": FEATURE_NAMES}, indent=2
        )
        + "\n",
        "hybrid_weights.json": json.dumps(HYBRID_WEIGHTS, indent=2) + "\n",
        "thresholds.json": json.dumps(
            {"email_probability": 0.5, "low": 25, "high": 50, "critical": 75},
            indent=2,
        )
        + "\n",
        "metrics.json": json.dumps(
            {
                "selected": {"name": "rules", "evaluation": "not trained"},
                "email_models": [],
                "user_risk": {},
                "note": "Deterministic offline rules bundle; never production-approved.",
            },
            indent=2,
        )
        + "\n",
        "model_card.md": (
            "# Offline rules demo model\n\n"
            "- Status: **demo**\n"
            "- Selected implementation: transparent metadata rules\n"
            "- Inputs: authentication, routing, sender relationship, and relay metadata only\n"
            "- Excluded: subject, body, preview, unique body, and attachment bytes\n"
            "- Intended use: local simulator demonstration only\n"
            "- Production release: prohibited; train and approve an immutable model bundle first\n"
        ),
    }
    for name, content in payloads.items():
        (output / name).write_text(content)
    manifest: dict[str, object] = {
        "version": "rules-demo-1",
        "created_at": datetime.now(UTC).isoformat(),
        "approved": False,
        "status": "demo",
        "selected_model": "rules",
        "selection_note": "Fresh-clone deterministic metadata-rules fallback.",
        "feature_version": "EmailMetadataV1",
        "behavior_feature_version": "UserDailyFeaturesV1",
        "metrics": json.loads(payloads["metrics.json"]),
        "artifacts": {name: digest(output / name) for name in payloads},
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    output = Path("artifacts/models/current")
    manifest = output / "manifest.json"
    if manifest.exists():
        print(f"Model bundle already present: {manifest}")
        return
    created = build(output)
    print(f"Created explicit {created['status']} bundle {created['version']} at {output}")


if __name__ == "__main__":
    main()
