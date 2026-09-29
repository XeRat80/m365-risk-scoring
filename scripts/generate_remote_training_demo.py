"""Create an explicitly synthetic V2 scan-format dataset for remote training demos."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

COMPONENTS = (
    "email_threat",
    "identity_compromise",
    "mfa_exposure",
    "privilege_exposure",
    "endpoint_threat",
)


def generate(output: Path, *, users: int = 100, days: int = 5, seed: int = 365) -> None:
    if users < 40 or days < 3:
        raise ValueError("Demo needs at least 40 users and three days")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    rng = random.Random(seed)
    subjects = list(range(users))
    attacked = set(rng.sample(subjects, max(10, users // 4)))
    feature_path = output / "feature_windows.jsonl"
    label_path = output / "generated_labels.csv"
    digest = hashlib.sha256()
    count = 0
    with (
        feature_path.open("x", encoding="utf-8") as features,
        label_path.open("x", newline="", encoding="utf-8") as labels,
    ):
        writer = csv.writer(labels)
        writer.writerow(["sample_id", "label"])
        for subject in subjects:
            subject_key = hashlib.sha256(f"demo-subject:{seed}:{subject}".encode()).hexdigest()
            is_admin = rng.random() < 0.08
            for day in range(days):
                compromised = subject in attacked and day >= days - 2
                # Include benign anomalies and subtle attacks so a synthetic
                # benchmark cannot appear perfectly separable by construction.
                email = rng.uniform(0.01, 0.40)
                identity = rng.uniform(0.01, 0.40)
                if rng.random() < 0.12:
                    email += rng.uniform(0.18, 0.42)
                if rng.random() < 0.12:
                    identity += rng.uniform(0.18, 0.42)
                if compromised:
                    intensity = 0.15 if rng.random() < 0.20 else rng.uniform(0.24, 0.55)
                    if subject % 3 != 1:
                        email += intensity
                    if subject % 3 != 0:
                        identity += intensity
                email = min(1.0, email)
                identity = min(1.0, identity)
                components = {
                    "email_threat": round(email, 4),
                    "identity_compromise": round(identity, 4),
                    "mfa_exposure": 0.0,
                    "privilege_exposure": 0.7 if is_admin else 0.0,
                    "endpoint_threat": None,
                }
                window_end = (datetime(2026, 9, 20, tzinfo=UTC) + timedelta(days=day)).isoformat()
                sample_id = hashlib.sha256(
                    f"demo-window:{subject_key}:{window_end}".encode()
                ).hexdigest()
                row = {
                    "sample_id": sample_id,
                    "subject_key": subject_key,
                    "window_end": window_end,
                    "feature_version": "UserFeatureWindowV2",
                    "model_version": "generated-fixture-v1",
                    "components": components,
                    "features": {
                        "email_top3": components["email_threat"],
                        "identity_time": components["identity_compromise"],
                    },
                    "availability": {
                        name: "unavailable" if name == "endpoint_threat" else "available"
                        for name in COMPONENTS
                    },
                }
                line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                features.write(line)
                digest.update(line.encode())
                writer.writerow([sample_id, int(compromised)])
                count += 1
    os.chmod(feature_path, 0o600)
    os.chmod(label_path, 0o600)
    manifest = {
        "schema": "scanned-feature-export-v1",
        "source_category": "generated",
        "labelled": True,
        "production_eligible": False,
        "ground_truth": "deterministic synthetic scenario schedule",
        "rows": count,
        "sha256": digest.hexdigest(),
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.chmod(manifest_path, 0o600)
    print(f"Generated {count} synthetic windows and separate labels in {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--users", type=int, default=100)
    parser.add_argument("--days", type=int, default=5)
    args = parser.parse_args()
    generate(args.out, users=args.users, days=args.days)


if __name__ == "__main__":
    main()
