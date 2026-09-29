#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    manifest = json.loads(Path("data/DATASET_MANIFEST.json").read_text())
    entries = [*manifest["public_datasets"], *manifest["generated_datasets"]]
    for entry in entries:
        path = Path(entry["path"])
        if not path.is_file():
            raise SystemExit(f"Dataset is missing: {path}")
        if path.stat().st_size != entry["bytes"]:
            raise SystemExit(f"Dataset size mismatch: {path}")
        if sha256(path) != entry["sha256"]:
            raise SystemExit(f"Dataset checksum mismatch: {path}")
    print(f"Verified {len(entries)} immutable dataset artifacts")


if __name__ == "__main__":
    main()
