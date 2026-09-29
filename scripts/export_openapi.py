#!/usr/bin/env python3
"""Export the deterministic FastAPI contract used by frontend type generation."""

from __future__ import annotations

import json
from pathlib import Path

from services.api.app.main import app


def main() -> None:
    Path("openapi.json").write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
