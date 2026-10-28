"""The agent image must own its build outputs, not rely on the build umask.

agent/Dockerfile runs `npm ci` and `npm run build` as root, so node_modules/
and dist/ are root-owned. The image then drops to USER node. That only works
while the builder leaves "other" read/execute bits on what root created —
which is a property of the BUILDER, not of the Dockerfile: buildkit's
docker-container driver produces 0770/0660 here, and the harness then fails to
load with `agent harness not found: /app/agent/dist/harness/cli.js`, a
permissions failure reported as a missing file.

The chown at the top of the Dockerfile cannot cover this: it runs before npm
creates either directory.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path("agent/Dockerfile").read_text()


def line_of(pattern: str) -> int:
    for n, line in enumerate(DOCKERFILE.splitlines(), 1):
        if re.search(pattern, line):
            return n
    raise AssertionError(f"agent/Dockerfile no longer contains {pattern!r}")


def test_build_outputs_are_chowned_to_node_after_the_npm_build():
    build = line_of(r"^RUN npm run build")
    chown = next(
        (
            n
            for n, line in enumerate(DOCKERFILE.splitlines(), 1)
            if n >= build and "chown -R node:node" in line
        ),
        None,
    )
    assert chown is not None, (
        "nothing chowns the root-created node_modules/ and dist/ to node after "
        "the npm build — USER node cannot read them on a builder that strips "
        "'other' permissions"
    )
    assert chown < line_of(r"^USER node")


def test_npm_npx_and_corepack_are_removed_after_the_prune():
    """npm's bundled packages carry fixable CVEs and nothing at runtime needs
    them, so the image removes them — but only after the prune that still
    calls npm.
    """
    prune = line_of(r"npm prune --omit=dev")
    removal = line_of(r"^RUN rm -rf /usr/local/lib/node_modules/npm\b")
    assert removal > prune, (
        "npm/npx/corepack are removed before the npm prune still needs them"
    )
    removed = "\n".join(DOCKERFILE.splitlines()[removal - 1 : line_of(r"^USER node") - 1])
    for name in ("npm", "npx", "corepack"):
        assert f"/usr/local/bin/{name}" in removed, (
            f"agent/Dockerfile does not remove /usr/local/bin/{name}"
        )
    for name in ("npm", "corepack"):
        assert f"/usr/local/lib/node_modules/{name}" in removed, (
            f"agent/Dockerfile does not remove /usr/local/lib/node_modules/{name}"
        )


def test_node_base_image_is_pinned_to_a_patched_22_release():
    """Every node base must be an exact 22.x.y at or above 22.23.4.

    A floating tag such as node:22-bookworm-slim does not name a patch
    release, so it cannot prove the bundled Brotli/zlib fix (CVE-2026-111497)
    is present.
    """
    minimum = (22, 23, 4)
    tags = re.findall(r"^FROM node:(\S+)", DOCKERFILE, re.MULTILINE)
    assert tags, "agent/Dockerfile has no FROM node:<tag> line"
    for tag in tags:
        m = re.match(r"(\d+)\.(\d+)\.(\d+)-", tag)
        assert m, f"node base {tag!r} does not pin an exact major.minor.patch"
        version = (int(m[1]), int(m[2]), int(m[3]))
        assert version[0] == 22 and version >= minimum, (
            f"node base {tag!r} is older than 22.23.4 or not a 22.x.y release"
        )
