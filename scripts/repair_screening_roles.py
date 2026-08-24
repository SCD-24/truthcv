"""Normalize the ``role`` field of screening records already on the volume.

Screening records written before the role-title check existed (and any brought
in by ``scripts/migrate_jobs_history.py``, whose store stays lenient about
titles) can carry a ``role`` that is merely messy -- wrapped across lines,
padded with whitespace, or fenced by stray separator punctuation. This one-off
maintenance script rewrites those to their normalized form so the Screenings
page shows a clean title, and it surfaces the records whose role cannot be made
usable at all so the operator can fix them by hand.

For each stored screening it computes ``normalize_role_title(role)`` and runs
``validate_role_title`` on the result:

* If validation fails, the stored role is board-noise, a pasted URL, blank, or
  otherwise unusable (MANUAL-REPAIR). It is **never** rewritten, even under
  ``--apply``: the operator needs to see what the agent actually wrote. It is
  reported with the validator's own message -- whether or not normalization
  would have changed it, so an already unusable role is surfaced rather than
  silently left alone.
* Otherwise, if the normalized value differs from the stored one, the record is
  FIXABLE and -- under ``--apply`` -- rewritten through
  ``screening.store.update`` (one call per record, so the store owns the atomic
  write and ``updated_at`` stamp).
* Otherwise the record already holds a clean, usable title and is left
  untouched (UNCHANGED).

It is **idempotent**: once ``--apply`` has run, every fixable record's stored
role already equals its normalized form, so a second ``--apply`` normalizes
nothing. The default is a dry run that writes nothing and only reports.

This script goes through ``screening.store`` for every read and write; it never
touches ``data/screenings.json`` directly.

Usage::

    python scripts/repair_screening_roles.py           # dry run, report only
    python scripts/repair_screening_roles.py --apply    # write the fixes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as ``python scripts/repair_screening_roles.py`` and Python puts scripts/
# on the path rather than the repo root, so the packages below would not
# resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402
from screening.role import normalize_role_title, validate_role_title  # noqa: E402


def classify(screenings: list) -> tuple[list, list, list]:
    """Bucket screenings into (unchanged, fixable, manual-repair).

    Every record's normalized role is validated. A role the validator rejects
    is manual-repair whether or not normalization changed it (so an already
    unusable role -- blank, board-noise, a URL -- is surfaced rather than
    silently left as "unchanged"). A role that validates is ``fixable`` when
    normalization changed the stored value and ``unchanged`` when it did not.
    ``fixable`` holds ``(screening, normalized)`` pairs; ``manual`` holds
    ``(screening, message)`` pairs carrying the validator's message.
    """
    unchanged, fixable, manual = [], [], []
    for s in screenings:
        normalized = normalize_role_title(s.role)
        try:
            validate_role_title(normalized)
        except ValueError as exc:
            manual.append((s, str(exc)))
        else:
            if normalized != (s.role or ""):
                fixable.append((s, normalized))
            else:
                unchanged.append(s)
    return unchanged, fixable, manual


def apply_fixes(fixable: list) -> None:
    """Write each fixable record's normalized role through the store."""
    for s, normalized in fixable:
        screening_store.update(s.id, {"role": normalized})


def print_report(unchanged: list, fixable: list, manual: list, applied: bool) -> None:
    """Print the three counts, one line per manual-repair record, and next step."""
    print("dry run (nothing written)" if not applied else "applied changes")
    print(f"unchanged: {len(unchanged)}")
    print(f"normalized: {len(fixable)}")
    print(f"needs-manual-repair: {len(manual)}")
    for s, message in manual:
        print(f"  {s.id} | {s.company} | {s.url} | {message}")
    print("You can now correct those roles on the Screenings page.")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write normalized roles; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, classify, optionally apply fixes, and print the report."""
    args = _parse_args(argv)
    unchanged, fixable, manual = classify(screening_store.load_all())
    if args.apply:
        apply_fixes(fixable)
    print_report(unchanged, fixable, manual, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
