"""Prepare .env so `docker compose up` can start the stack.

Run inside a container by the per-OS launcher scripts:

    docker run --rm -v "<repo>:/work" -w /work python:3-alpine \\
        python -m launcher --repo /work

Standard library only — the image installs no packages.

Output contract: everything a human reads goes to stderr, and stdout carries
exactly one machine-readable KEY=value line, so a shell shim can read the port
with a single `cut` and never has to parse prose.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import envfile, ports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launcher")
    parser.add_argument("--repo", default=".", help="Repository root holding .env")
    parser.add_argument(
        "--bump",
        metavar="VAR",
        default="",
        help="Advance this host port variable to its next candidate",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    env_path = repo / ".env"

    if args.bump:
        return _bump(env_path, args.bump)

    required = {
        "ENCRYPTION_KEY": envfile.generate_encryption_key(),
        "AGENT_API_TOKEN": envfile.generate_agent_token(),
        "APP_PORT": str(ports.default_for("APP_PORT")),
    }
    try:
        result = envfile.ensure(env_path, repo / ".env.example", required)
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    _report(result)
    print(f"APP_PORT={result.values.get('APP_PORT', '')}")
    return 0


def _bump(env_path: Path, variable: str) -> int:
    """Advance one host port variable past a port Docker refused to bind."""
    if variable not in ports.DEFAULTS:
        print(f"Unknown port variable: {variable}", file=sys.stderr)
        return 2
    if not env_path.exists():
        print("No .env to bump — run without --bump first.", file=sys.stderr)
        return 2

    try:
        values = envfile.parse(env_path.read_text(encoding="utf-8"))
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    current = int(values.get(variable) or ports.default_for(variable))
    reserved = {
        int(value)
        for key, value in values.items()
        if key in ports.DEFAULTS and key != variable and value.isdigit()
    }
    try:
        advanced = ports.bump(current, reserved)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2

    try:
        backup_path = envfile.set_value(env_path, variable, str(advanced))
    except OSError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(
        f"{variable} {current} was already in use; trying {advanced}. "
        f"Previous .env saved to {backup_path.name}.",
        file=sys.stderr,
    )
    print(f"{variable}={advanced}")
    return 0


def _report(result: envfile.EnsureResult) -> None:
    """Say exactly what changed, so nothing happens to .env silently."""
    if result.created:
        print("Created .env from .env.example.", file=sys.stderr)
    if result.backup_path is not None:
        print(f"Existing .env saved to {result.backup_path.name}.", file=sys.stderr)
    for key in result.filled:
        print(f"Filled in {key} (it was blank).", file=sys.stderr)
    for key in result.appended:
        print(f"Added {key}.", file=sys.stderr)
    if not (result.created or result.filled or result.appended):
        print("Configuration already complete; nothing changed.", file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
