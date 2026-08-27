"""Every local package imported by code shipped in the app image must itself
be shipped — otherwise the container fails to start (import error) instead of
a test failing at build time.

Regression coverage for the "missing onboarding COPY" incident: api/routes.py
imports onboarding.store, but the Dockerfile's app stage never copied
onboarding/ into the image, so the container crashed on start.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile"

EXTRA_LOCAL_MODULES: set[str] = set()


def _local_packages() -> set[str]:
    """Top-level repo directories that are real Python packages."""
    packages = set()
    for child in REPO_ROOT.iterdir():
        if child.is_dir() and (child / "__init__.py").is_file():
            packages.add(child.name)
    return packages


def _app_stage_text() -> str:
    """The Dockerfile text for the runtime ('app') build stage only."""
    text = DOCKERFILE.read_text()
    stages = re.split(r"(?m)^FROM ", text)
    for stage in stages:
        if stage.lstrip().startswith("python") and " AS app" in stage.splitlines()[0]:
            return stage
    raise AssertionError("Could not find 'FROM python:... AS app' stage in Dockerfile")


def _shipped_packages() -> set[str]:
    """Packages/modules the Dockerfile app stage actually COPYs in."""
    stage = _app_stage_text()
    shipped = set()
    for name in re.findall(r"^COPY\s+(\S+)/\s+\./\1/\s*$", stage, flags=re.MULTILINE):
        shipped.add(name)
    if re.search(r"^COPY\s+datafile\.py\s+\./\s*$", stage, flags=re.MULTILINE):
        shipped.add("datafile")
    return shipped


def _imported_local_roots(package_dir: Path, local_packages: set[str]) -> set[str]:
    """Root package/module names imported (at any indentation) by .py files
    under package_dir, restricted to names that are local repo packages."""
    roots = set()
    for py_file in package_dir.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root in local_packages:
                        roots.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative import within the same package
                if node.module:
                    root = node.module.split(".")[0]
                    if root in local_packages:
                        roots.add(root)
    return roots


def test_dockerfile_ships_every_locally_imported_package():
    local_packages = _local_packages() | EXTRA_LOCAL_MODULES
    shipped = _shipped_packages()

    assert shipped, "No COPY lines found for the app stage — Dockerfile parsing likely broken"

    missing: dict[str, set[str]] = {}
    for name in sorted(shipped):
        package_dir = REPO_ROOT / name
        if not package_dir.is_dir():
            continue  # e.g. datafile — a single module, not scannable as a package dir
        imported = _imported_local_roots(package_dir, local_packages)
        unshipped = imported - shipped
        if unshipped:
            missing[name] = unshipped

    assert not missing, (
        "Shipped package(s) import local package(s) that the Dockerfile app "
        f"stage does not COPY: {missing}"
    )
