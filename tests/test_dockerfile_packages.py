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
REQUIREMENTS = REPO_ROOT / "requirements.txt"
BROTLI_MIN_VERSION = (1, 2, 1)
NODE_MIN_VERSION = (22, 23, 4)
PIP_TOOLING_PINS = {"setuptools": "84.2.1", "wheel": "0.48.0"}

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


def _web_stage_text() -> str:
    """The Dockerfile text for the frontend build ('web') stage only."""
    text = DOCKERFILE.read_text()
    stages = re.split(r"(?m)^FROM ", text)
    for stage in stages:
        if stage.lstrip().startswith("node") and " AS web" in stage.splitlines()[0]:
            return stage
    raise AssertionError("Could not find 'FROM node:... AS web' stage in Dockerfile")


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


def test_brotli_pin_is_at_least_cve_fixed_version():
    """brotli below 1.2.1 carries the CVE-2026-111497 decoder out-of-bounds write."""
    match = re.search(r"^brotli==([\d.]+)\s*$", REQUIREMENTS.read_text(), flags=re.MULTILINE)
    assert match, "requirements.txt has no exact brotli==<version> pin"
    version = tuple(int(part) for part in match.group(1).split("."))
    assert version >= BROTLI_MIN_VERSION, (
        f"brotli pinned to {match.group(1)}; CVE-2026-111497 fix requires "
        f">= {'.'.join(map(str, BROTLI_MIN_VERSION))}"
    )


def test_web_stage_node_is_exact_patched_22_tag():
    """Node bundles brotli; the web build stage must pin an exact Node 22.x.y at or above the CVE fix."""
    match = re.search(r"^FROM node:(\S+) AS web\s*$", DOCKERFILE.read_text(), flags=re.MULTILINE)
    assert match, "Dockerfile has no 'FROM node:<tag> AS web' stage"
    version = re.fullmatch(r"22\.(\d+)\.(\d+)(?:-slim)?", match.group(1))
    assert version, f"web stage tag {match.group(1)!r} is not an exact 22.x.y tag"
    found = (22, int(version.group(1)), int(version.group(2)))
    assert found >= NODE_MIN_VERSION, (
        f"web stage uses node {match.group(1)}; CVE-2026-111497 fix requires "
        f">= {'.'.join(map(str, NODE_MIN_VERSION))}"
    )


def test_app_stage_installs_libbrotli1_explicitly():
    """The app stage's apt-get install must name libbrotli1 so the CVE-2026-111497 fix build is pulled."""
    installs = re.findall(r"apt-get install\b(?:\\\n|[^\n])*", _app_stage_text())
    assert any(re.search(r"\blibbrotli1\b", block) for block in installs), (
        "app stage apt-get install does not name libbrotli1 (CVE-2026-111497)"
    )


def test_app_stage_pins_pip_tooling_before_requirements():
    """setuptools and wheel must be exact pins, installed before requirements.txt (setuptools vendors jaraco.context; wheel is flagged by Trivy)."""
    stage = _app_stage_text()
    tooling = re.search(
        r"^RUN pip install --no-cache-dir (setuptools==\S+ wheel==\S+)\s*$",
        stage,
        flags=re.MULTILINE,
    )
    assert tooling, "app stage has no 'RUN pip install --no-cache-dir setuptools==<v> wheel==<v>' line"
    pins = dict(pin.split("==", 1) for pin in tooling.group(1).split())
    assert pins == PIP_TOOLING_PINS, f"app stage pip tooling pins are {pins}; expected {PIP_TOOLING_PINS}"
    requirements_install = stage.index("pip install --no-cache-dir -r requirements.txt")
    assert tooling.start() < requirements_install, (
        "pip tooling pins must be installed before 'pip install -r requirements.txt'"
    )


def test_web_stage_pins_exact_npm_before_install():
    """The web build stage must upgrade npm to an exact 11.x.y pin before its npm install."""
    stage = _web_stage_text()
    match = re.search(r"^RUN npm install -g npm@(\S+)\s*$", stage, flags=re.MULTILINE)
    assert match, "web stage has no 'RUN npm install -g npm@<version>' line"
    assert re.fullmatch(r"11\.\d+\.\d+", match.group(1)), (
        f"web stage npm pin {match.group(1)!r} is not an exact 11.x.y version"
    )
    npm_install = re.search(r"^RUN npm install\s*$", stage, flags=re.MULTILINE)
    assert npm_install, "web stage has no 'RUN npm install' line"
    assert match.start() < npm_install.start(), "npm pin must run before 'RUN npm install'"
