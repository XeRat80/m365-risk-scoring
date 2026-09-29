"""Portable, unapproved user-risk training experiment for remote CPU servers.

Runs with Python 3.11+ and numpy, scikit-learn, and joblib. This is deliberately
separate from the production model promotion path: labels must be supplied by
an analyst, and no scan output is ever treated as its own ground truth.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

COMPONENTS = (
    "email_threat",
    "identity_compromise",
    "mfa_exposure",
    "privilege_exposure",
    "endpoint_threat",
)
VECTOR_NAMES = tuple(
    field
    for component in COMPONENTS
    for field in (
        f"{component}__value",
        f"{component}__available",
        f"{component}__insufficient_history",
    )
)


def load_export(
    path: Path, public_notebook: bool
) -> tuple[list[dict[str, object]], dict[str, object]]:
    manifest_path = path.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "scanned-feature-export-v1":
        raise ValueError("Unsupported scan export schema")
    if public_notebook and manifest.get("source_category") != "generated":
        raise ValueError(
            "Public notebooks accept generated demo exports only; keep company data private"
        )
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
        raise ValueError("Feature export checksum mismatch")
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if len(rows) != manifest.get("rows"):
        raise ValueError("Feature export row count mismatch")
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate sample ID in scan export")
    return rows, manifest


def load_labels(path: Path) -> dict[str, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not {"sample_id", "label"}.issubset(reader.fieldnames):
            raise ValueError("Labels CSV needs sample_id,label columns")
        labels: dict[str, int] = {}
        for row in reader:
            sample_id = str(row["sample_id"])
            label = str(row["label"])
            if label not in {"0", "1"} or sample_id in labels:
                raise ValueError("Labels must be unique 0/1 values")
            labels[sample_id] = int(label)
    return labels


def vector(row: dict[str, object]) -> list[float]:
    components = row.get("components")
    coverage = row.get("availability")
    if not isinstance(components, dict) or not isinstance(coverage, dict):
        raise ValueError("Each row needs components and availability")
    values: list[float] = []
    for name in COMPONENTS:
        status = coverage.get(name)
        if status not in {"available", "unavailable", "insufficient_history"}:
            raise ValueError(f"Invalid availability for {name}: {status}")
        value = components.get(name)
        available = status == "available" and value is not None
        if available and (not isinstance(value, (float, int)) or not 0 <= value <= 1):
            raise ValueError(f"Invalid component value for {name}")
        values.extend(
            [
                float(value) if available else 0.0,
                float(available),
                float(status == "insufficient_history"),
            ]
        )
    return values


def split_groups(
    rows: list[dict[str, object]], y: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    groups = np.asarray([str(row["subject_key"]) for row in rows])
    unique_groups = np.unique(groups)
    group_labels = np.asarray([int(y[groups == group].max()) for group in unique_groups])
    if min(np.bincount(group_labels, minlength=2)) < 5:
        raise ValueError(
            "Need at least five positive and five negative subjects for grouped evaluation"
        )
    train_val_groups, test_groups = train_test_split(
        unique_groups, test_size=0.2, random_state=42, stratify=group_labels
    )
    train_val_labels = np.asarray([int(y[groups == group].max()) for group in train_val_groups])
    train_groups, val_groups = train_test_split(
        train_val_groups, test_size=0.25, random_state=42, stratify=train_val_labels
    )
    train_idx = np.flatnonzero(np.isin(groups, train_groups))
    val_idx = np.flatnonzero(np.isin(groups, val_groups))
    test_idx = np.flatnonzero(np.isin(groups, test_groups))
    for name, idx in (("train", train_idx), ("validation", val_idx), ("test", test_idx)):
        if len(np.unique(y[idx])) < 2:
            raise ValueError(f"{name} split has only one class; collect more reviewed examples")
    return train_idx, val_idx, test_idx


def metrics(y: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, object]:
    predicted = (probability >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, predicted, labels=[0, 1]).ravel()
    return {
        "samples": int(len(y)),
        "positives": int(y.sum()),
        "precision": float(precision_score(y, predicted, zero_division=0)),
        "recall": float(recall_score(y, predicted, zero_division=0)),
        "pr_auc": float(average_precision_score(y, probability)),
        "roc_auc": float(roc_auc_score(y, probability)),
        "brier": float(brier_score_loss(y, probability)),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
        "tp": int(tp),
    }


def choose_threshold(y: np.ndarray, probability: np.ndarray) -> float:
    choices = []
    for threshold in np.unique(probability):
        predicted = probability >= threshold
        precision = precision_score(y, predicted, zero_division=0)
        recall = recall_score(y, predicted, zero_division=0)
        if recall >= 0.75:
            choices.append((precision, recall, float(threshold)))
    return max(choices)[2] if choices else 0.5


def train(
    features: Path, labels_path: Path, output: Path, public_notebook: bool
) -> dict[str, object]:
    rows, source = load_export(features, public_notebook)
    labels = load_labels(labels_path)
    selected = [row for row in rows if row["sample_id"] in labels]
    if len(selected) < 30:
        raise ValueError("Need at least 30 separately labelled feature windows")
    versions = {str(row["feature_version"]) for row in selected}
    if versions != {"UserFeatureWindowV2"}:
        raise ValueError(f"Expected one UserFeatureWindowV2 schema; found {sorted(versions)}")
    x = np.asarray([vector(row) for row in selected], dtype=float)
    y = np.asarray([labels[str(row["sample_id"])] for row in selected], dtype=int)
    train_idx, val_idx, test_idx = split_groups(selected, y)
    candidates = {
        "logistic": make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced")
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=200,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        ),
    }
    selected_name = ""
    selected_model = None
    selected_probability = None
    best = (-1.0, -1.0)
    for name, model in candidates.items():
        model.fit(x[train_idx], y[train_idx])
        probability = model.predict_proba(x[val_idx])[:, 1]
        rank = (
            float(average_precision_score(y[val_idx], probability)),
            -float(brier_score_loss(y[val_idx], probability)),
        )
        if rank > best:
            selected_name, selected_model, selected_probability, best = (
                name,
                model,
                probability,
                rank,
            )
    assert selected_model is not None and selected_probability is not None
    threshold = choose_threshold(y[val_idx], selected_probability)
    test_probability = selected_model.predict_proba(x[test_idx])[:, 1]
    report: dict[str, object] = {
        "status": "experimental_unapproved",
        "source_category": source["source_category"],
        "feature_version": "UserFeatureWindowV2",
        "model": selected_name,
        "selection_metric": "validation_pr_auc",
        "threshold": threshold,
        "subject_disjoint_split": True,
        "chronological_validation": False,
        "train_samples": int(len(train_idx)),
        "validation": metrics(y[val_idx], selected_probability, threshold),
        "test": metrics(y[test_idx], test_probability, threshold),
        "input_sha256": source["sha256"],
        "label_sha256": hashlib.sha256(labels_path.read_bytes()).hexdigest(),
        "trained_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "limitation": "Labels and source representativeness require independent review; this does not approve production inference.",
    }
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    joblib.dump(
        {"model": selected_model, "feature_names": VECTOR_NAMES, "threshold": threshold},
        output / "model.joblib",
    )
    os.chmod(output / "model.joblib", 0o600)
    report_fd = os.open(output / "report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(report_fd, "w", encoding="utf-8") as destination:
        destination.write(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train and test an experimental user-risk model from a scanned feature export"
    )
    parser.add_argument("--features", required=True, type=Path)
    parser.add_argument(
        "--labels", required=True, type=Path, help="Separate analyst-reviewed sample_id,label CSV"
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--public-notebook",
        action="store_true",
        help="Reject anything except generated demo exports",
    )
    args = parser.parse_args()
    try:
        report = train(args.features, args.labels, args.out, args.public_notebook)
    except (ValueError, KeyError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
