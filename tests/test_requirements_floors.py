"""Security floors for runtime pins in requirements.txt (Oct 2026 dependency
audit). Each package must be pinned at or above the release that fixes its
known CVEs."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REQUIREMENTS = Path(__file__).resolve().parent.parent / "requirements.txt"

FLOORS = {
    "pypdf": (6, 21, 3),
    "pyjwt": (2, 15, 1),
    "mcp": (2, 3, 0),
    "certifi": (2026, 10, 23),
    "opentelemetry-api": (1, 45, 1),
    "pillow": (13, 0, 0),
    "weasyprint": (70, 0),
}


def _pinned_version(name: str) -> tuple[int, ...]:
    match = re.search(
        rf"^{re.escape(name)}(?:\[[^\]]*\])?==([\d.]+)\s*$",
        REQUIREMENTS.read_text(),
        flags=re.MULTILINE | re.IGNORECASE,
    )
    assert match, f"{name} is not pinned with == in requirements.txt"
    return tuple(int(part) for part in match.group(1).split("."))


@pytest.mark.parametrize("name,floor", FLOORS.items())
def test_pin_meets_security_floor(name, floor):
    version = _pinned_version(name)
    assert version >= floor, (
        f"{name} pinned at {'.'.join(map(str, version))}, "
        f"needs >= {'.'.join(map(str, floor))}"
    )
