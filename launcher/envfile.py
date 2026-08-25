"""Read and safely update the project's .env file.

Bootstrap runs before the stack starts and must never destroy an existing
configuration — the maintainer's own or a colleague's. Only three writes are
performed: creating the file when it is absent, filling a blank assignment in
place, and appending a key that is absent entirely. A line carrying a value is
never touched, so comments, ordering and content survive — except that line
endings are normalised to LF on any write, since every write reassembles the
file with `"\n".join(...)`.

`set_value` is the single exception, reserved for the port variables the
launcher owns; see its docstring for why that is safe.
"""

from __future__ import annotations

import base64
import os
import secrets
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MANAGED_HEADER = "# --- added by the TruthCV launcher ---"


def parse(text: str) -> dict[str, str]:
    """KEY=VALUE pairs from .env text; comments and blank lines ignored.

    A leading `export ` (as in a line meant to be sourced by a shell) is
    stripped from the key, and an inline comment — a `#` preceded by
    whitespace — ends the value, matching `docker compose`'s own reading of
    the file. A `#` with no preceding whitespace is part of the value, since
    a password may legitimately contain one.
    """
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        stripped = _strip_export(stripped)
        key, _, value = stripped.partition("=")
        values[key.strip()] = _strip_inline_comment(value).strip()
    return values


def _strip_export(stripped: str) -> str:
    """Drop a leading `export` keyword, as used in a line meant to be sourced."""
    if stripped.startswith("export") and stripped[6:7] in (" ", "\t"):
        return stripped[6:].lstrip()
    return stripped


def _strip_inline_comment(value: str) -> str:
    """Cut off an inline comment: a `#` preceded by whitespace."""
    for index, char in enumerate(value):
        if char == "#" and index > 0 and value[index - 1] in (" ", "\t"):
            return value[:index]
    return value


def generate_encryption_key() -> str:
    """A Fernet key, identical in construction to `api.genkey`'s output."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


def generate_agent_token() -> str:
    """The shared secret the app and agent authenticate to each other with."""
    return secrets.token_hex(32)


def backup(path: Path) -> Path:
    """Copy `path` beside itself with a UTC timestamp; returns the copy."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = path.with_name(f"{path.name}.backup-{stamp}")
    shutil.copy2(path, destination)
    return destination


@dataclass
class EnsureResult:
    """What `ensure` did, so the caller can report it precisely."""

    created: bool = False
    filled: list[str] = field(default_factory=list)
    appended: list[str] = field(default_factory=list)
    backup_path: Path | None = None
    values: dict[str, str] = field(default_factory=dict)


def ensure(env_path: Path, example_path: Path, required: dict[str, str]) -> EnsureResult:
    """Guarantee every key in `required` has a non-blank value in `.env`.

    `required` maps each key to the value to use *only if* it is missing or
    blank. A key that already carries a value keeps it, and the supplied value
    is discarded — re-running never rotates a live secret.
    """
    if not env_path.exists():
        lines = example_path.read_text(encoding="utf-8").splitlines()
        filled, appended = _apply(lines, required)
        text = "\n".join(lines) + "\n"
        env_path.write_text(text, encoding="utf-8")
        return EnsureResult(created=True, filled=filled, appended=appended, values=parse(text))

    original = env_path.read_text(encoding="utf-8")
    existing = parse(original)
    missing = {key: value for key, value in required.items() if not existing.get(key)}
    if not missing:
        # Nothing to do, and the file is not opened for writing at all.
        return EnsureResult(values=existing)

    backup_path = backup(env_path)
    lines = original.splitlines()
    filled, appended = _apply(lines, missing)
    text = "\n".join(lines) + "\n"
    env_path.write_text(text, encoding="utf-8")
    return EnsureResult(
        filled=filled, appended=appended, backup_path=backup_path, values=parse(text)
    )


def set_value(env_path: Path, key: str, value: str) -> Path:
    """Rewrite one key's line in place, backing the file up first.

    This is the only function that changes a line carrying a value. It is
    reserved for the port variables the launcher owns, and is called only after
    Docker itself has refused to bind the current port — so the value being
    replaced is already known not to work. Returns the backup's path.
    """
    backup_path = backup(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.partition("=")[0].strip() == key:
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return backup_path


def _apply(lines: list[str], required: dict[str, str]) -> tuple[list[str], list[str]]:
    """Fill blank assignments in place and append keys absent entirely.

    Mutates `lines`. Returns (filled keys, appended keys). Filling in place
    rather than appending is what keeps each key appearing exactly once: the
    shipped `.env.example` carries blank `ENCRYPTION_KEY=` and
    `AGENT_API_TOKEN=` lines, and appending past them would emit each key
    twice and make correctness depend on compose resolving duplicates.
    """
    filled: list[str] = []
    appended: list[str] = []
    for key, value in required.items():
        index = _blank_assignment_index(lines, key)
        if index is None:
            appended.append(key)
        else:
            lines[index] = f"{key}={value}"
            filled.append(key)
    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(MANAGED_HEADER)
        lines.extend(f"{key}={required[key]}" for key in appended)
    return filled, appended


def _blank_assignment_index(lines: list[str], key: str) -> int | None:
    """Index of a `KEY=` line carrying no value, or None."""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        stripped = _strip_export(stripped)
        name, _, value = stripped.partition("=")
        if name.strip() == key and not value.strip():
            return index
    return None
