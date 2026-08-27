#!/usr/bin/env python3
"""Render APPLICATION_LOG.md from the live application ledger.

Replaces the retired Jobs repo's `bin/render-log`. Reads every application via
the tracker's own store and writes the Markdown log to the data volume, under
`log/` rather than the volume root.

That subdirectory keeps the log off `GET /api/download/{name}`, which serves
the volume root by bare filename with no authentication and rejects any name
containing a path separator. Treat it as tidiness, NOT as a security control:
the same personal data is already served from the volume root under guessable
names (`applications.json`, `answers.yaml`, `canonical_cv.pdf`), and the SPA
catch-all route resolves `..` without a containment check. Both are
pre-existing and are recorded in docs/jobs-retirement-audit.md.

Refuses to write, leaving the previous log untouched, if the rendered text
does not account for every application exactly once, or if the ledger did not
load whole.

Usage:
    python scripts/render_application_log.py [--output PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from applications import store as app_store  # noqa: E402
from applications.log_render import RenderRefused, render_log, write_log  # noqa: E402
from companyresearch import store as findings_store  # noqa: E402
from storage import data_dir  # noqa: E402


def default_log_path() -> Path:
    """The log's home on the data volume, one directory below the root."""
    return data_dir() / "log" / "APPLICATION_LOG.md"


def check_ledger_loaded_whole(applications: list) -> None:
    """Refuse to render unless the ledger loaded completely.

    `store.load_all()` fails SAFE — a missing, unreadable or malformed
    `applications.json` yields an empty list, and non-dict entries are dropped
    silently. That is right for an API that should keep serving, and wrong
    here: the completeness guard is vacuously satisfied by an empty list, so a
    transient read error would atomically replace a log accounting for every
    application with a header and nothing else, print "Rendered 0
    applications", and exit 0. Silent omission is the one failure this whole
    module exists to prevent, and its likeliest cause is upstream of the guard.

    So compare against the raw file: if it holds more records than were
    loaded, something was dropped and the previous log must stand.
    """
    ledger = app_store.applications_path()
    if not ledger.exists():
        if applications:
            return
        raise RenderRefused(f"ledger not found at {ledger} — refusing to render an empty log")

    try:
        raw = json.loads(ledger.read_text())
    except (json.JSONDecodeError, OSError) as error:
        raise RenderRefused(f"ledger at {ledger} could not be read: {error}") from error

    if not isinstance(raw, list):
        raise RenderRefused(f"ledger at {ledger} is not a list of records")

    if len(raw) != len(applications):
        raise RenderRefused(
            f"ledger holds {len(raw)} records but only {len(applications)} loaded — "
            "refusing to render a log that would omit the rest"
        )


def main(argv: list[str] | None = None) -> int:
    """Render the ledger to the log file; return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=None, help="Destination path.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render and report, but do not write.",
    )
    args = parser.parse_args(argv)

    applications = app_store.load_all()
    target = Path(args.output) if args.output else default_log_path()

    findings_by_company: dict[str, list] = {}
    for finding in findings_store.load_all():
        findings_by_company.setdefault(finding.company, []).append(finding)

    try:
        check_ledger_loaded_whole(applications)
        if args.dry_run:
            rendered = render_log(applications, findings_by_company)
            print(f"{len(applications)} applications -> {len(rendered)} chars (not written)")
            return 0
        written = write_log(applications, target, findings_by_company)
    except RenderRefused as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return 1
    print(f"Rendered {len(applications)} applications to {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
