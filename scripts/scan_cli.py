"""Small command-line client for the local M365 risk API.

The CLI never asks for a Microsoft password or stores an access token. A real
tenant requires an authorized token from the organization's own deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

DEMO_TENANT = "00000000-0000-4000-8000-000000000001"


class CliError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise CliError("--api must be an HTTP(S) URL without embedded credentials")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise CliError("Use HTTPS for a non-local API so the bearer token stays private")
        self.base_url = base_url.rstrip("/")
        self.token = token

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        body = json.dumps(payload).encode() if payload is not None else None
        request_headers = {"Accept": "application/json", **(headers or {})}
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        request = Request(  # noqa: S310 - URL scheme and host are validated in __init__.
            f"{self.base_url}{path}", data=body, headers=request_headers, method=method
        )
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - validated URL.
                decoded = json.load(response)
        except HTTPError as exc:
            try:
                detail = json.load(exc).get("message", exc.reason)
            except (ValueError, AttributeError):
                detail = exc.reason
            raise CliError(f"API returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise CliError(f"Cannot reach {self.base_url}: {exc}") from exc
        if not isinstance(decoded, dict):
            raise CliError("API returned an unexpected response")
        return decoded


def authenticate(client: ApiClient, demo: bool, tenant: str, token_env: str) -> None:
    if demo:
        result = client.request(
            "POST", "/api/v1/auth/mock-token", {"tenant_id": tenant, "role": "admin"}
        )
        client.token = str(result["access_token"])
        return
    token = os.environ.get(token_env)
    if not token:
        raise CliError(
            f"Set {token_env} to an authorized admin bearer token; do not pass tokens on the command line"
        )
    client.token = token


def wait_for_job(client: ApiClient, job_id: str, timeout: int) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_status = "queued"
    while time.monotonic() < deadline:
        cursor: str | None = None
        found: dict[str, object] | None = None
        for _ in range(20):
            query = urlencode({"limit": 100, **({"cursor": cursor} if cursor else {})})
            page = client.request("GET", f"/api/v1/sync/jobs?{query}")
            found = next((item for item in page.get("items", []) if item.get("id") == job_id), None)
            if found or not page.get("next_cursor"):
                break
            cursor = str(page["next_cursor"])
        if not found:
            raise CliError(f"Synchronization job {job_id} disappeared")
        last_status = str(found.get("status", "unknown"))
        if last_status == "completed":
            return found
        if last_status == "dead":
            raise CliError(f"Synchronization failed: {found.get('error') or 'check worker logs'}")
        time.sleep(2)
    raise CliError(f"Timed out after {timeout}s; job {job_id} is {last_status}")


def collect(client: ApiClient, output: Path) -> tuple[int, str]:
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise CliError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(output, 0o700)
    features_path = output / "feature_windows.jsonl"
    cursor: str | None = None
    category: str | None = None
    count = 0
    seen: set[str] = set()
    digest = hashlib.sha256()
    features_fd = os.open(features_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(features_fd, "w", encoding="utf-8") as destination:
        while True:
            query = urlencode({"limit": 500, **({"cursor": cursor} if cursor else {})})
            page = client.request("GET", f"/api/v1/datasets/scanned?{query}")
            source = str(page["source_category"])
            if category is not None and category != source:
                raise CliError("Source category changed during export")
            category = source
            for row in page.get("items", []):
                if not isinstance(row, dict) or not isinstance(row.get("sample_id"), str):
                    raise CliError("Invalid scanned feature row")
                if row["sample_id"] in seen:
                    raise CliError("Repeated feature window during pagination; rerun the export")
                seen.add(row["sample_id"])
                line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                destination.write(line)
                digest.update(line.encode())
                count += 1
            cursor = str(page["next_cursor"]) if page.get("next_cursor") else None
            if not cursor:
                break
    manifest = {
        "schema": "scanned-feature-export-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "source_category": category,
        "labelled": False,
        "production_eligible": False,
        "rows": count,
        "feature_file": features_path.name,
        "sha256": digest.hexdigest(),
        "note": "No risk score or incident label is included. Analyst-reviewed labels are separate.",
    }
    manifest_fd = os.open(output / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(manifest_fd, "w", encoding="utf-8") as destination:
        destination.write(json.dumps(manifest, indent=2) + "\n")
    return count, str(category)


def fetch_results(client: ApiClient, top: int) -> dict[str, object]:
    summary = client.request("GET", "/api/v1/dashboard/summary")
    users: list[dict[str, object]] = []
    cursor: str | None = None
    while True:
        query = urlencode({"limit": 100, **({"cursor": cursor} if cursor else {})})
        page = client.request("GET", f"/api/v1/users?{query}")
        items = page.get("items")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise CliError("API returned an invalid user result page")
        users.extend(items)
        if len(users) > 100_000:
            raise CliError("Too many users for the CLI summary; query the paginated API directly")
        cursor = str(page["next_cursor"]) if page.get("next_cursor") else None
        if not cursor:
            break
    ranked = sorted(users, key=lambda item: float(item.get("score") or 0), reverse=True)
    return {
        "users": summary.get("users"),
        "risk_bands": {
            level: summary.get(level) for level in ("critical", "high", "medium", "low")
        },
        "average_score": summary.get("average_score"),
        "last_sync_at": summary.get("last_sync_at"),
        "top_users": [
            {
                "user_id": item.get("id"),
                "score": item.get("score"),
                "level": item.get("level"),
                "calculated_at": item.get("calculated_at"),
            }
            for item in ranked[:top]
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan and export content-free Microsoft 365 risk features"
    )
    parser.add_argument("command", choices=["scan", "collect", "identify", "results"])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Company-local API URL")
    parser.add_argument("--demo", action="store_true", help="Use local Mock Graph admin login")
    parser.add_argument("--tenant", default=DEMO_TENANT, help="Mock tenant UUID (with --demo)")
    parser.add_argument(
        "--token-env",
        default="M365_RISK_TOKEN",
        help="Environment variable holding a real admin token",
    )
    parser.add_argument("--out", type=Path, help="New private output directory for feature export")
    parser.add_argument(
        "--scan-only", action="store_true", help="Start a scan without exporting features"
    )
    parser.add_argument(
        "--user-id", help="Local employee ID to resolve to a sample ID with identify"
    )
    parser.add_argument("--timeout", type=int, default=180, help="Seconds to wait for a scan")
    parser.add_argument(
        "--show-results", action="store_true", help="Print latest scores after a scan"
    )
    parser.add_argument("--top", type=int, default=10, help="Number of highest-risk users to show")
    args = parser.parse_args()
    if args.scan_only and args.command != "scan":
        parser.error("--scan-only is only valid for scan")
    if args.command in {"scan", "collect"} and not args.scan_only and not args.out:
        parser.error("--out is required unless --scan-only is selected")
    if args.command == "identify" and not args.user_id:
        parser.error("identify requires --user-id")
    if args.show_results and args.command != "scan":
        parser.error("--show-results is only valid for scan")
    if not 1 <= args.top <= 100:
        parser.error("--top must be between 1 and 100")
    try:
        client = ApiClient(args.api)
        authenticate(client, args.demo, args.tenant, args.token_env)
        if args.command == "identify":
            row = client.request(
                "GET", f"/api/v1/datasets/scanned/subjects/{quote(args.user_id, safe='')}"
            )
            print(
                json.dumps(
                    {
                        "sample_id": row["sample_id"],
                        "subject_key": row["subject_key"],
                        "window_end": row["window_end"],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "results":
            print(json.dumps(fetch_results(client, args.top), indent=2))
            return 0
        if args.command == "scan":
            print("Starting metadata scan and feature engineering...", flush=True)
            job = client.request(
                "POST", "/api/v1/sync", headers={"Idempotency-Key": str(uuid.uuid4())}
            )
            completed = wait_for_job(client, str(job["id"]), args.timeout)
            print(f"Scan completed: job {completed['id']}")
        if not args.scan_only:
            count, category = collect(client, args.out)
            print(f"Exported {count} feature windows ({category}) to {args.out}")
            print("The export has no incident labels and cannot approve a production model.")
        if args.show_results:
            print(json.dumps(fetch_results(client, args.top), indent=2))
        return 0
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
