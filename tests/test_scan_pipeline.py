from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from scripts.scan_cli import collect, fetch_results
from scripts.train_scanned import COMPONENTS, load_export, train


class FakeClient:
    def request(self, method: str, path: str) -> dict[str, object]:
        assert method == "GET"
        assert path.startswith("/api/v1/datasets/scanned?")
        return {
            "items": [
                {
                    "sample_id": "sample-a",
                    "subject_key": "subject-a",
                    "window_end": "2026-09-29T00:00:00Z",
                    "feature_version": "UserFeatureWindowV2",
                    "model_version": "demo",
                    "components": {name: 0.0 for name in COMPONENTS},
                    "features": {"email_top3": 0.0},
                    "availability": {name: "available" for name in COMPONENTS},
                }
            ],
            "next_cursor": None,
            "source_category": "generated",
        }


def test_cli_collects_content_free_rows_with_manifest(tmp_path: Path) -> None:
    output = tmp_path / "scan"
    count, category = collect(FakeClient(), output)  # type: ignore[arg-type]
    assert (count, category) == (1, "generated")
    rows, manifest = load_export(output / "feature_windows.jsonl", public_notebook=True)
    assert len(rows) == 1
    assert manifest["labelled"] is False
    assert manifest["production_eligible"] is False


def test_cli_results_rank_users_across_pages_without_display_names() -> None:
    class ResultsClient:
        def request(self, method: str, path: str) -> dict[str, object]:
            assert method == "GET"
            if path == "/api/v1/dashboard/summary":
                return {
                    "users": 3,
                    "critical": 1,
                    "high": 1,
                    "medium": 0,
                    "low": 1,
                    "average_score": 54.0,
                    "last_sync_at": "2026-09-30T00:00:00Z",
                }
            if "cursor=" in path:
                return {
                    "items": [
                        {
                            "id": "user-003",
                            "display_name": "Private",
                            "score": 99,
                            "level": "critical",
                        }
                    ],
                    "next_cursor": None,
                }
            return {
                "items": [
                    {"id": "user-001", "display_name": "Private", "score": 10, "level": "low"},
                    {"id": "user-002", "display_name": "Private", "score": 53, "level": "high"},
                ],
                "next_cursor": "next-page",
            }

    result = fetch_results(ResultsClient(), top=2)  # type: ignore[arg-type]
    assert result["risk_bands"] == {"critical": 1, "high": 1, "medium": 0, "low": 1}
    assert [item["user_id"] for item in result["top_users"]] == [  # type: ignore[index]
        "user-003",
        "user-002",
    ]
    assert "Private" not in json.dumps(result)


def test_remote_training_uses_separate_labels_and_grouped_holdout(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    scan.mkdir()
    lines = []
    labels = []
    for index in range(60):
        positive = int(index >= 30)
        sample_id = f"sample-{index:03d}"
        row = {
            "sample_id": sample_id,
            "subject_key": f"subject-{index:03d}",
            "window_end": "2026-09-29T00:00:00Z",
            "feature_version": "UserFeatureWindowV2",
            "model_version": "demo",
            "components": {name: float(positive) for name in COMPONENTS},
            "features": {},
            "availability": {name: "available" for name in COMPONENTS},
        }
        lines.append(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        labels.append((sample_id, positive))
    payload = "".join(lines).encode()
    features = scan / "feature_windows.jsonl"
    features.write_bytes(payload)
    (scan / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "scanned-feature-export-v1",
                "source_category": "generated",
                "rows": 60,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    )
    label_file = tmp_path / "labels.csv"
    with label_file.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["sample_id", "label"])
        writer.writerows(labels)
    report = train(features, label_file, tmp_path / "trained", public_notebook=True)
    assert report["status"] == "experimental_unapproved"
    assert report["subject_disjoint_split"] is True
    assert report["test"]["samples"] > 0  # type: ignore[index]
    assert (tmp_path / "trained" / "model.joblib").exists()


def test_public_notebook_rejects_real_scan_data(tmp_path: Path) -> None:
    export = tmp_path / "scan"
    export.mkdir()
    (export / "feature_windows.jsonl").write_text("")
    (export / "manifest.json").write_text(
        json.dumps(
            {
                "schema": "scanned-feature-export-v1",
                "source_category": "real_unlabelled",
                "rows": 0,
                "sha256": hashlib.sha256(b"").hexdigest(),
            }
        )
    )
    with pytest.raises(ValueError, match="Public notebooks"):
        load_export(export / "feature_windows.jsonl", public_notebook=True)
