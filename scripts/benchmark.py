#!/usr/bin/env python3
"""Local read-latency and metadata-processing acceptance benchmark."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid

import httpx

TENANT = "00000000-0000-4000-8000-000000000001"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--mock", default="http://127.0.0.1:8081")
    parser.add_argument("--events", type=int, default=1000)
    args = parser.parse_args()
    async with httpx.AsyncClient(timeout=30) as client:
        login = await client.post(
            f"{args.api}/api/v1/auth/mock-token",
            json={"tenant_id": TENANT, "role": "admin"},
        )
        login.raise_for_status()
        auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
        reset = await client.post(
            f"{args.api}/api/v1/simulations/reset",
            headers={**auth, "Idempotency-Key": f"benchmark-reset-{uuid.uuid4()}"},
        )
        reset.raise_for_status()
        timings: list[float] = []
        for _ in range(100):
            started = time.perf_counter()
            response = await client.get(f"{args.api}/api/v1/dashboard/summary", headers=auth)
            response.raise_for_status()
            timings.append(1000 * (time.perf_counter() - started))
        burst = await client.post(
            f"{args.mock}/__admin/burst",
            params={"count": args.events, "scenario": "credential-phishing"},
            headers={"X-Mock-Admin": "local-admin-secret-change-me", "X-Tenant-ID": TENANT},
        )
        burst.raise_for_status()
        key = f"benchmark-{uuid.uuid4()}"
        started = time.perf_counter()
        job = await client.post(
            f"{args.api}/api/v1/sync", headers={**auth, "Idempotency-Key": key}
        )
        job.raise_for_status()
        job_id = job.json()["id"]
        status = "queued"
        while time.perf_counter() - started < 120:
            jobs = await client.get(f"{args.api}/api/v1/sync/jobs", headers=auth)
            jobs.raise_for_status()
            match = next(item for item in jobs.json()["items"] if item["id"] == job_id)
            status = match["status"]
            if status in {"completed", "dead"}:
                break
            await asyncio.sleep(0.25)
        elapsed = time.perf_counter() - started
    p95 = statistics.quantiles(timings, n=100)[94]
    throughput = args.events / elapsed * 60
    result = {
        "read_p95_ms": round(p95, 2),
        "events": args.events,
        "job_status": status,
        "processing_seconds": round(elapsed, 2),
        "events_per_minute": round(throughput, 1),
        "passes": status == "completed" and p95 < 300 and throughput >= 1000,
    }
    print(json.dumps(result, indent=2))
    if not result["passes"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
