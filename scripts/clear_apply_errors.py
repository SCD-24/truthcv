"""Clear a stale apply failure from one or more screening records.

``screening.store.record_apply_failure`` accumulates an operator-facing
``apply_error`` (and, when structured, ``apply_blocker``/``signin_url``) every
time an unattended run fails to submit an approved application. Most of the
time that failure describes something true about the posting or the run and
should stay on the record. Occasionally it describes an environment fault
that has since been fixed — e.g. the browser container's upload sandbox
rejecting ``get_canonical_cv``'s path — in which case the text is stale: the
next run will succeed, but the ledger still shows the old failure until
something clears it.

``screening.store`` has no HTTP or MCP route for this on purpose (clearing an
error is an operator repair, not something the agent or the app UI does for
itself), so this one-off script is the supported way to do it, calling
``screening.store.clear_apply_failure`` for each id given. It touches nothing
else: ``approval``, ``apply_attempts``, and claim fields are left exactly as
``clear_apply_failure`` leaves them.

This script goes through ``screening.store`` for every read and write; it
never touches ``data/screenings.json`` directly.

Usage::

    python scripts/clear_apply_errors.py <id> [<id> ...]             # dry run, report only
    python scripts/clear_apply_errors.py --apply <id> [<id> ...]     # write the fixes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as ``python scripts/clear_apply_errors.py`` and Python puts scripts/ on
# the path rather than the repo root, so the packages below would not
# resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402


def classify(ids: list[str]) -> tuple[list, list]:
    """Split the requested ids into (found, missing) screening records.

    ``found`` holds the actual ``Screening`` objects (read via
    ``screening.store.get``, before any write); ``missing`` holds the ids that
    matched nothing.
    """
    found, missing = [], []
    for screening_id in ids:
        screening = screening_store.get(screening_id)
        if screening is None:
            missing.append(screening_id)
        else:
            found.append(screening)
    return found, missing


def apply_fixes(found: list, applied: bool) -> None:
    """Clear each found record's apply failure, when ``applied`` is true."""
    if not applied:
        return
    for screening in found:
        screening_store.clear_apply_failure(screening.id)


def print_report(found: list, missing: list, applied: bool) -> None:
    """Print what was (or would be) cleared, and which ids matched nothing."""
    print("dry run (nothing written)" if not applied else "applied changes")
    for screening in found:
        had_error = screening.apply_error or screening.apply_blocker or screening.signin_url
        verb = "cleared" if applied else "would clear"
        print(
            f"  {screening.id} | {screening.company} | {screening.role} | "
            f"approval={screening.approval!r} | attempts={screening.apply_attempts} | "
            f"{verb}: apply_error={screening.apply_error!r} "
            f"apply_blocker={screening.apply_blocker!r} signin_url={screening.signin_url!r}"
            + ("" if had_error else " (already empty)")
        )
    for screening_id in missing:
        print(f"  {screening_id} | NOT FOUND")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one or more screening ids, and one ``--apply`` flag."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("ids", nargs="+", help="screening id(s) to clear")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the cleared fields; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Look up the given ids, optionally clear their apply failures, and report."""
    args = _parse_args(argv)
    found, missing = classify(args.ids)
    apply_fixes(found, args.apply)
    print_report(found, missing, args.apply)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
