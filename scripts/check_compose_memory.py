#!/usr/bin/env python3
"""Enforce the local Compose memory acceptance limit."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

LIMIT_BYTES = 8 * 1024**3
UNITS = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
}


def parse_size(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", value)
    if not match or match.group(2).upper() not in UNITS:
        raise ValueError(f"Unsupported Docker memory value: {value}")
    return round(float(match.group(1)) * UNITS[match.group(2).upper()])


def main() -> None:
    docker = shutil.which("docker")
    if not docker:
        raise SystemExit("Docker executable was not found")
    completed = subprocess.run(  # noqa: S603 - resolved absolute Docker executable
        [docker, "stats", "--no-stream", "--format", "{{json .}}"],
        check=True,
        capture_output=True,
        text=True,
    )
    services: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        item = json.loads(line)
        name = str(item.get("Name", ""))
        if name.startswith("m365-risk-"):
            usage = str(item["MemUsage"]).split("/")[0]
            services[name] = parse_size(usage)
    if not services:
        raise SystemExit("No running m365-risk Compose services were found")
    total = sum(services.values())
    result = {
        "services_mib": {
            name: round(value / 1024**2, 2) for name, value in sorted(services.items())
        },
        "total_mib": round(total / 1024**2, 2),
        "limit_mib": round(LIMIT_BYTES / 1024**2),
        "passes": total < LIMIT_BYTES,
    }
    print(json.dumps(result, indent=2))
    if total >= LIMIT_BYTES:
        raise SystemExit("Compose memory acceptance limit exceeded")


if __name__ == "__main__":
    main()
