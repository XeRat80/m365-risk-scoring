from __future__ import annotations

import pytest

from scripts.check_compose_memory import parse_size


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("512B", 512),
        ("1 KiB", 1024),
        ("2.5MiB", round(2.5 * 1024**2)),
        ("1GB", 1000**3),
    ],
)
def test_docker_memory_values_are_parsed(value: str, expected: int) -> None:
    assert parse_size(value) == expected


def test_unknown_memory_unit_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        parse_size("3 widgets")
