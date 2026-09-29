#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def assess_bundle(manifest_path: Path) -> tuple[bool, list[str]]:
    manifest: dict[str, Any] = json.loads(manifest_path.read_text())
    metrics = manifest.get("metrics", {})
    selected = metrics.get("selected", {})
    rules = next(
        (item for item in metrics.get("email_models", []) if item.get("name") == "rules"),
        {},
    )
    user = metrics.get("user_risk", {})
    parity_limit = 1e-5 if manifest.get("selected_model") == "logistic" else 1e-4
    checks = {
        "email PR-AUC is at least 0.90": selected.get("pr_auc", -1) >= 0.90,
        "email PR-AUC beats rules by at least 0.03": selected.get("pr_auc", -1)
        >= rules.get("pr_auc", 2) + 0.03,
        "precision is at least 0.85": selected.get("precision", -1) >= 0.85,
        "recall is at least 0.80": selected.get("recall", -1) >= 0.80,
        "Brier score is at most 0.10": selected.get("brier", 2) <= 0.10,
        "ECE is at most 0.05": selected.get("ece", 2) <= 0.05,
        "user top-10% recall is at least 0.80": user.get("top_10_recall", -1) >= 0.80,
        "false alerts are at most 5 per 100 users": user.get("false_alerts_per_100", 101) <= 5,
        "median detection delay is at most one day": user.get("median_detection_delay_days", 999) <= 1,
        "joblib/ONNX parity is within the model limit": metrics.get("onnx_max_abs_difference", 1)
        <= parity_limit,
    }
    failures = [name for name, passed in checks.items() if not passed]
    for filename, expected in manifest.get("artifacts", {}).items():
        artifact = manifest_path.parent / filename
        if not artifact.is_file():
            failures.append(f"artifact is missing: {filename}")
            continue
        actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"artifact checksum differs: {filename}")
    declared = manifest.get("approved") is True and manifest.get("status") == "approved"
    if declared != (not failures):
        failures.append("manifest approval state does not match recomputed gates")
    return not failures and declared, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, nargs="?", default=Path("artifacts/models/current/manifest.json"))
    parser.add_argument("--require-approved", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    approved, failures = assess_bundle(args.manifest)
    print(json.dumps({"version": manifest["version"], "approved": manifest["approved"], "metrics": manifest["metrics"]}, indent=2))
    if failures:
        print(json.dumps({"gate_failures": failures}, indent=2))
    if args.require_approved and not approved:
        raise SystemExit("Model promotion gates failed or the bundle is inconsistent; bundle remains demo-only")


if __name__ == "__main__":
    main()
