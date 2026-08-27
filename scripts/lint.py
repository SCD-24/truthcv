#!/usr/bin/env python3
"""Repository lint gate: compile-check every Python file it is given.

The project pins no third-party linter (see requirements-dev.txt), so the
lint gate is a dependency-free static check: each Python file is parsed and
compiled, which catches syntax errors, bad indentation and invalid literals
without importing anything or running any project code.

Usage::

    python scripts/lint.py                # check every tracked .py file
    python scripts/lint.py a.py b.md      # check the .py files among these

Non-Python paths are ignored (the checks runner appends whatever files a
change touched), as are paths that no longer exist, so a deletion never
fails the gate. Exits 0 when everything compiles, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are never source: build output, caches, vendored deps.
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "data",
    ".venv",
    "venv",
}


def tracked_python_files() -> list[Path]:
    """Every Python file tracked by git, or a filesystem walk if git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "*.py"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        paths = [REPO_ROOT / line for line in out.splitlines() if line.strip()]
        if paths:
            return paths
    except (OSError, subprocess.CalledProcessError):
        pass
    return [p for p in REPO_ROOT.rglob("*.py") if not _is_excluded(p)]


def _is_excluded(path: Path) -> bool:
    """True when the path sits inside a directory that is never project source."""
    return any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def selected_files(argv: list[str]) -> list[Path]:
    """The Python files to check: the given paths filtered to .py, else everything tracked."""
    if not argv:
        return tracked_python_files()
    return [Path(arg) for arg in argv if arg.endswith(".py")]


def compile_check(path: Path) -> str | None:
    """Compile one file; return a one-line error description, or None when it is clean."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        return f"{path}: cannot read ({exc})"
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        line = exc.lineno if exc.lineno is not None else 0
        return f"{path}:{line}: {exc.msg}"
    except ValueError as exc:
        return f"{path}: {exc}"
    return None


def main(argv: list[str]) -> int:
    """Run the compile check over the selected files and report every failure."""
    files = [p for p in selected_files(argv) if p.exists() and not _is_excluded(p)]
    errors = [err for err in (compile_check(p) for p in files) if err]

    for err in errors:
        print(err, file=sys.stderr)

    if errors:
        print(f"lint: {len(errors)} error(s) in {len(files)} file(s)", file=sys.stderr)
        return 1

    print(f"lint: {len(files)} file(s) OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
