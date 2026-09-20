#!/usr/bin/env python3
"""Run TruthCV's checks (lint or test) from any checkout, including a forest
worktree.

A git worktree gets the tracked files and nothing else: no .venv, and no
web/node_modules or agent/node_modules. Both live beside the MAIN checkout
and are shared, so this script resolves the main checkout from git's common
dir and links the node_modules directories in if they are missing (the
symlink convention .gitignore already documents) rather than reinstalling
hundreds of megabytes per worktree.

This is Python, not bash, because Python is the one runtime already required
by the backend on every OS; bash, `ln -s` and `.venv/bin` are not portable to
Windows, where this script also needs to run.

Usage::

    scripts/check.py lint
    scripts/check.py test         (all three suites)
    scripts/check.py test-python
    scripts/check.py test-web
    scripts/check.py test-agent
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def git_out(*args: str) -> str:
    """Run a git command and return its stripped stdout."""
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def run(cmd: list[str]) -> int:
    """Print then run a command, returning its exit code."""
    print("+ " + " ".join(cmd), file=sys.stderr)
    return subprocess.run(cmd, check=False).returncode


def link_node_modules(repo_root: Path, main_root: Path, pkg: str) -> None:
    """Symlink (or, on Windows without privilege, junction) pkg/node_modules
    from the main checkout into a worktree that lacks its own copy."""
    if repo_root == main_root:
        return
    link = repo_root / pkg / "node_modules"
    target = main_root / pkg / "node_modules"
    if link.exists() or not target.is_dir():
        return
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(target)],
                check=True,
                capture_output=True,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            pass
    print(
        f"check.py: could not link {pkg}/node_modules; run `npm ci` in {pkg}/",
        file=sys.stderr,
    )


def find_pytest(main_root: Path) -> list[str]:
    """The main checkout's venv pytest, else the current interpreter's -m pytest."""
    name = "Scripts/pytest.exe" if os.name == "nt" else "bin/pytest"
    pytest_bin = main_root / ".venv" / name
    if pytest_bin.is_file() and os.access(pytest_bin, os.X_OK):
        return [str(pytest_bin)]
    return [sys.executable, "-m", "pytest"]


def find_npm() -> str:
    """npm on PATH, or exit 1 — there is no bundled fallback."""
    npm = shutil.which("npm")
    if npm is None:
        print("check.py: npm not found on PATH", file=sys.stderr)
        sys.exit(1)
    return npm


def main(argv: list[str]) -> int:
    subcommand = argv[0] if argv else ""
    if subcommand not in {"lint", "test", "test-python", "test-web", "test-agent"}:
        print(
            "usage: scripts/check.py {lint|test|test-python|test-web|test-agent}",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(git_out("rev-parse", "--show-toplevel")).resolve()
    os.chdir(repo_root)
    main_root = (
        Path(git_out("rev-parse", "--path-format=absolute", "--git-common-dir")).parent
    ).resolve()

    link_node_modules(repo_root, main_root, "web")
    link_node_modules(repo_root, main_root, "agent")

    pytest_cmd = find_pytest(main_root) + ["-q"]
    npm = find_npm()

    commands: list[list[str]]
    if subcommand == "lint":
        commands = [
            [npm, "--prefix", "web", "run", "typecheck"],
            [npm, "--prefix", "agent", "run", "typecheck"],
        ]
    elif subcommand == "test":
        commands = [
            pytest_cmd,
            [npm, "--prefix", "web", "run", "test"],
            [npm, "--prefix", "agent", "run", "test"],
        ]
    elif subcommand == "test-python":
        commands = [pytest_cmd]
    elif subcommand == "test-web":
        commands = [[npm, "--prefix", "web", "run", "test"]]
    else:
        commands = [[npm, "--prefix", "agent", "run", "test"]]

    for cmd in commands:
        code = run(cmd)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
