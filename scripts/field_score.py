"""Offline experimental scoring of a privacy-reduced real Graph scan."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from packages.ml.m365risk_ml.runtime import ModelRuntime
from packages.ml.m365risk_ml.v2 import CanonicalSignal, score_components, top_k_mean


class ScoreError(Exception):
    pass


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ScoreError(f"Missing scan file: {path.name}")
    with path.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ScoreError(f"Invalid scan file: {path.name}")
    return rows


def write_private(path: Path, payload: object, *, lines: bool = False) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        if lines:
            for row in payload:  # type: ignore[union-attr]
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
        else:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")


def score_scan(scan_dir: Path, model_dir: Path) -> dict[str, Any]:
    if (scan_dir / "scores.jsonl").exists() or (scan_dir / "score_report.json").exists():
        raise ScoreError("Score output already exists; create a new scan rather than overwriting it")
    manifest = json.loads((scan_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "real-graph-collection-v1" or manifest.get("mode") != "collection":
        raise ScoreError("This directory is not a completed real Graph collection")
    canonical_rows = read_jsonl(scan_dir / "canonical_features.jsonl")
    mail_rows = read_jsonl(scan_dir / "mail_features.jsonl")
    if len(canonical_rows) != manifest.get("selected_users"):
        raise ScoreError("Canonical row count does not match the scan manifest")
    runtime = ModelRuntime.load(model_dir)
    if runtime.onnx_session is None or runtime.approved:
        raise ScoreError("Expected the bundled, unapproved field research ONNX model")
    mail_by_user: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in mail_rows:
        mail_by_user[str(row["sample_id"])].append(row)
    results: list[dict[str, Any]] = []
    for row in canonical_rows:
        sample_id = str(row["sample_id"])
        window_end = datetime.fromisoformat(str(row["window_end"]))
        cutoff = window_end - timedelta(days=30)
        probabilities: list[float] = []
        for mail in mail_by_user.get(sample_id, []):
            received = datetime.fromisoformat(str(mail["received_at"]).replace("Z", "+00:00"))
            if received.tzinfo is None:
                received = received.replace(tzinfo=UTC)
            if received < cutoff or received > window_end:
                continue
            features = mail.get("model_features")
            if not isinstance(features, dict):
                raise ScoreError("Mail model features are missing")
            fallback = {
                "replyToDomainMismatch": bool(mail.get("reply_to_domain_mismatch")),
                "fromSenderMismatch": bool(mail.get("from_sender_mismatch")),
                "receivedHops": int(features.get("received_hops") or 0),
                "externalSender": bool(mail.get("external_sender")),
            }
            probabilities.append(runtime.predict(features, fallback))
        email_signal = top_k_mean(probabilities)
        canonical = row.get("canonical")
        if not isinstance(canonical, dict):
            raise ScoreError("Canonical signal data is missing")
        components: dict[str, CanonicalSignal] = {"email_threat": email_signal}
        for name in ("identity_compromise", "mfa_exposure", "privilege_exposure", "endpoint_threat"):
            value = canonical.get(name)
            if not isinstance(value, dict):
                raise ScoreError(f"Missing canonical signal: {name}")
            components[name] = CanonicalSignal(
                value=value.get("value"),
                availability=value.get("availability"),
                explanation=str(value.get("explanation") or ""),
            )
        scored = score_components(components)
        results.append({
            "sample_id": sample_id,
            "window_end": row["window_end"],
            "score": scored.score,
            "level": scored.level,
            "components": scored.components,
            "availability": scored.coverage,
            "contributions": scored.contributions,
            "email_model": {
                "version": runtime.version,
                "status": runtime.status,
                "reviewed_mails_30d": len(probabilities),
                "highest_probability": max(probabilities) if probabilities else None,
            },
            "review_candidate": scored.score is not None and scored.score >= 50,
            "decision_status": "experimental_analyst_review_only",
        })
    report = {
        "schema": "real-graph-field-score-v1",
        "source_scan": str(scan_dir.name),
        "users": len(results),
        "scored_users": sum(row["score"] is not None for row in results),
        "insufficient_data_users": sum(row["score"] is None for row in results),
        "email_model_version": runtime.version,
        "email_model_approved": False,
        "user_score_method": "canonical signal fusion; not a trained user-compromise model",
        "source_coverage": manifest.get("source_coverage"),
        "alert_policy": "review_candidate is not a Microsoft or SOC alert",
    }
    write_private(scan_dir / "scores.jsonl", results, lines=True)
    write_private(scan_dir / "score_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a local real Graph scan using canonical features")
    parser.add_argument("--scan-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, default=Path("/app/bundles/field-research"))
    args = parser.parse_args()
    try:
        report = score_scan(args.scan_dir, args.model_dir)
        print(json.dumps(report, indent=2))
        return 0
    except (ScoreError, OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
