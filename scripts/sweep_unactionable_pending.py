"""Reject pending screenings that have no posting text and no draft to act on.

Before ``screening.posting.validate_posting_text`` became a precondition for
new records (and before ``screening.store.create`` stopped queueing
``not_found``/``expired`` blockers), the legacy importer
(``scripts/migrate_jobs_history.py``) and the pre-guard agent could leave a
record sitting in the operator's Found queue (``approval == "pending"``) with
an empty ``posting_text`` and nothing for the operator to act on: no posting
to read, and no cover-letter draft already written against it.

For each stored screening:

* If ``approval == "pending"`` AND ``posting_text`` is blank after stripping
  AND it has no saved cover-letter draft (the same definition used elsewhere:
  a draft with only whitespace text does not count), the
  record is SWEPT — under ``--apply`` its approval is rewritten to
  ``"rejected"`` through ``screening.store.set_approval``. There is nothing to
  draft from and nothing left for the operator to decide.
* If it is pending, has blank posting text, but DOES have a saved draft, it is
  KEPT (has a draft): a draft already exists, so the record is still
  actionable and is never written.
* Every other record (not pending, or has posting text) is UNTOUCHED.

This script goes through ``screening.store`` and ``coverletter.store`` for
every read and write; it never touches ``data/screenings.json`` or
``data/cover_letters/`` directly.

Running the sweep a second time recovers nothing further: a swept record's
approval is no longer ``"pending"``, so it no longer matches the sweep
condition — this script is **idempotent**. The default is a dry run that
writes nothing and only reports.

Usage::

    python scripts/sweep_unactionable_pending.py           # dry run, report only
    python scripts/sweep_unactionable_pending.py --apply    # write the fixes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as ``python scripts/sweep_unactionable_pending.py`` and Python puts
# scripts/ on the path rather than the repo root, so the packages below would
# not resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import coverletter.store as letter_store  # noqa: E402
import screening.store as screening_store  # noqa: E402


def _has_draft(screening_id: str) -> bool:
    """Whether a cover-letter draft exists for this screening.

    Mirrors ``api/routes.py``'s ``_has_draft`` exactly: a draft with only
    whitespace text does not count as a draft.
    """
    draft = letter_store.load(screening_id)
    return draft is not None and bool(draft.text.strip())


def classify(screenings: list) -> tuple[list, list, list]:
    """Split records into (swept, kept_with_draft, untouched).

    A record is swept when it is pending, its posting_text is blank after
    stripping, and it has no saved cover-letter draft. A pending, blank-text
    record WITH a draft is kept rather than swept: the draft is already
    actionable. Everything else is untouched.
    """
    swept, kept, untouched = [], [], []
    for s in screenings:
        if s.approval != "pending" or (s.posting_text or "").strip():
            untouched.append(s)
        elif _has_draft(s.id):
            kept.append(s)
        else:
            swept.append(s)
    return swept, kept, untouched


def apply_fixes(swept: list, applied: bool) -> None:
    """Reject every swept record's approval, when ``applied`` is true."""
    if not applied:
        return
    for s in swept:
        screening_store.set_approval(s.id, "rejected")


def print_report(swept: list, kept: list, untouched: list, applied: bool) -> None:
    """Print the three bucket counts, and one line per swept/kept record."""
    print("dry run (nothing written)" if not applied else "applied changes")
    print(f"swept (rejected — no posting text, no draft): {len(swept)}")
    for s in swept:
        print(f"  {s.id} | {s.company} | {s.role}")
    print(f"kept (has a draft): {len(kept)}")
    for s in kept:
        print(f"  {s.id} | {s.company} | {s.role}")
    print(f"untouched: {len(untouched)}")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="reject the swept records; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, classify, optionally apply fixes, and print the report."""
    args = _parse_args(argv)
    swept, kept, untouched = classify(screening_store.load_all())
    apply_fixes(swept, args.apply)
    print_report(swept, kept, untouched, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
