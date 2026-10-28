"""The browser image must sit on a patched Playwright base and pin its MCP.

browser/Dockerfile inherits Node from the mcr.microsoft.com/playwright base
image. CVE-2026-111497 (a Brotli decoder out-of-bounds write bundled in Node)
is fixed only in newer base tags, so the tag may not fall below v1.64.1.
@playwright/mcp decides which paths browser_file_upload may resolve, so it must
be pinned to an exact version rather than floating.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (REPO_ROOT / "browser" / "Dockerfile").read_text()

MIN_PLAYWRIGHT = (1, 64, 1)


def test_playwright_base_image_is_patched():
    """The FROM tag is at least v1.64.1."""
    match = re.search(
        r"^FROM\s+mcr\.microsoft\.com/playwright:v(\d+)\.(\d+)\.(\d+)\b",
        DOCKERFILE,
        re.MULTILINE,
    )
    assert match, "browser/Dockerfile has no FROM mcr.microsoft.com/playwright:vX.Y.Z"
    version = tuple(int(g) for g in match.groups())
    assert version >= MIN_PLAYWRIGHT, f"playwright base {version} < {MIN_PLAYWRIGHT}"


def test_playwright_mcp_is_pinned_to_an_exact_version():
    """npm install -g @playwright/mcp@x.y.z, never ^, ~, latest or bare."""
    match = re.search(r"npm install -g\s+@playwright/mcp(\S*)", DOCKERFILE)
    assert match, "browser/Dockerfile no longer installs @playwright/mcp"
    assert re.fullmatch(r"@\d+\.\d+\.\d+", match.group(1)), (
        f"@playwright/mcp must be pinned exactly, got {match.group(1)!r}"
    )
