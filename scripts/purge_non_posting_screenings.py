"""Delete screening records whose URL is not a job posting.

LinkedIn search/listing pages (``linkedin.com`` URLs that are not
``/jobs/view/<id>``) were once recorded as if they were postings. This one-off
script removes them via ``screening.store.delete_many`` (which also removes
each record's orphaned cover-letter draft).

Records the operator has acted on (approval ``applied`` or ``approved``) are
never deleted; they are listed for manual review instead.

**Stop the agent and back up ``data/screenings.json`` first** — deletion
cannot be reversed:

    cp data/screenings.json data/screenings.json.bak
    docker compose stop agent
    python scripts/purge_non_posting_screenings.py --apply
    docker compose start agent

Afterwards run ``scripts/dedupe_screenings.py`` to merge uk./www. copies of
the same job under the new LinkedIn dedupe key.

Usage::

    python scripts/purge_non_posting_screenings.py          # dry run
    python scripts/purge_non_posting_screenings.py --apply  # delete
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as a script, Python puts scripts/ on the path rather than the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402
from screening.url import is_posting_url  # noqa: E402

_PROTECTED_APPROVALS = frozenset({"applied", "approved"})


def plan(screenings: list) -> tuple[list, list]:
    """Return ``(deletable, needs_review)`` among non-posting records."""
    deletable: list = []
    review: list = []
    for s in screenings:
        if is_posting_url(getattr(s, "url", "") or ""):
            continue
        if getattr(s, "approval", "") in _PROTECTED_APPROVALS:
            review.append(s)
        else:
            deletable.append(s)
    return deletable, review


def _print_group(label: str, records: list) -> None:
    """Print one line per record under ``label``."""
    for s in records:
        print(f"  {label} {s.id} | approval={s.approval or '(none)'} | {s.url}")


def print_report(deletable: list, review: list, total: int, applied: bool) -> None:
    """Print every affected record, then the totals."""
    verb = "deleted" if applied else "would delete"
    _print_group("DROP  ", deletable)
    _print_group("REVIEW", review)
    print(f"\nscreenings loaded: {total}")
    print(f"records {verb}: {len(deletable)}")
    print(f"records needing manual review (not deleted): {len(review)}")
    if not applied and deletable:
        print("\ndry run — nothing was written. Re-run with --apply.")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete the records; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, plan the purge, optionally apply it, and report."""
    args = _parse_args(argv)
    screenings = screening_store.load_all()
    deletable, review = plan(screenings)
    if args.apply and deletable:
        screening_store.delete_many([s.id for s in deletable])
    print_report(deletable, review, len(screenings), args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
