"""Collapse the screening records that predate the one-posting-one-record rule.

``screening.store.create`` used to append unconditionally, so every scheduled
run re-screened postings it had already judged and filed a fresh record for
each. The operator's decision lives in ``approval`` on ONE record, so the
copies came back to the approval queue however many times they were rejected —
one Grafana Labs job accumulated ten records, nine of them rejected by hand.

The store now refuses the second record (``create_or_get``). This one-off
script cleans up what the old behaviour already wrote.

Records are grouped by ``screening.url.posting_dedupe_key`` — the same key the
store now enforces on — and each group keeps exactly one record. Records whose
URL has no key (blank, or no http(s) scheme and host: the legacy importer is
the one writer that can produce those) are never grouped and never deleted,
because the store cannot tell two of them apart either.

The keeper is the record carrying the furthest-advanced decision, ties broken
by the newest ``created_at``:

    applied > approved > rejected > pending > no decision recorded

Decision order, not date order alone: keeping the newest outright would keep an
undecided ``pending`` copy over the ``rejected`` one the operator actually
decided, which puts the posting straight back in the approval queue and leaves
the reported symptom in place.

Deletion goes through ``screening.store.delete_many``, so each removed record's
orphaned cover-letter draft goes with it. This script never touches
``data/screenings.json`` directly.

**Stop the agent before running with ``--apply``**, and back the file up — this
deletes records, and unlike the repair scripts it cannot be reversed by running
it again:

    cp data/screenings.json data/screenings.json.bak
    docker compose stop agent
    python scripts/dedupe_screenings.py --apply
    docker compose start agent

Usage::

    python scripts/dedupe_screenings.py           # dry run, report only
    python scripts/dedupe_screenings.py --apply    # delete the duplicates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Run as ``python scripts/dedupe_screenings.py`` and Python puts scripts/ on
# the path rather than the repo root, so the packages below would not resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402
from screening.url import posting_dedupe_key  # noqa: E402

# Furthest-advanced decision wins. An unknown approval value sorts with "no
# decision" rather than raising: a hand-edited file must not stop the cleanup,
# and the worst case is that such a record loses to one the operator did act on.
_DECISION_RANK = {"applied": 4, "approved": 3, "rejected": 2, "pending": 1, "": 0}


def _rank(screening) -> tuple:
    """Sort key: decision first, then recency. Higher is the better keeper."""
    return (
        _DECISION_RANK.get(getattr(screening, "approval", ""), 0),
        getattr(screening, "created_at", "") or "",
    )


def group_by_posting(screenings: list) -> dict:
    """Map each resolvable posting key to the records that claim it.

    Records with no key are omitted entirely — they are not a group of one,
    they are outside the rule.
    """
    groups: dict = {}
    for s in screenings:
        key = posting_dedupe_key(getattr(s, "url", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(s)
    return groups


def plan(screenings: list) -> list[tuple]:
    """One ``(keeper, [duplicates])`` pair per posting that has duplicates.

    Groups of one produce nothing: there is no cleanup to do and reporting
    them would bury the 27 that matter under 200 that do not.
    """
    duplicated = []
    for key, group in group_by_posting(screenings).items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=_rank, reverse=True)
        duplicated.append((ordered[0], ordered[1:]))
    return sorted(duplicated, key=lambda pair: (pair[0].company, pair[0].role))


def print_report(duplicated: list[tuple], total: int, applied: bool) -> None:
    """Print every group, then the totals. Kept verbose on purpose: this
    deletes records, so the dry run has to show which ones."""
    removals = sum(len(dupes) for _, dupes in duplicated)
    verb = "deleted" if applied else "would delete"
    for keeper, dupes in duplicated:
        print(f"\n{keeper.company} | {keeper.role}")
        print(f"  {keeper.url}")
        print(
            f"  KEEP   {keeper.id} | {keeper.created_at} | "
            f"verdict={keeper.verdict or '(none)'} | "
            f"approval={keeper.approval or '(none)'}"
        )
        for d in dupes:
            print(
                f"  DROP   {d.id} | {d.created_at} | "
                f"verdict={d.verdict or '(none)'} | "
                f"approval={d.approval or '(none)'}"
            )
    print(f"\nscreenings loaded: {total}")
    print(f"postings with duplicates: {len(duplicated)}")
    print(f"records {verb}: {removals}")
    if not applied and removals:
        print("\ndry run — nothing was written. Re-run with --apply.")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete the duplicate records; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, plan the collapse, optionally apply it, and report."""
    args = _parse_args(argv)
    screenings = screening_store.load_all()
    duplicated = plan(screenings)
    if args.apply:
        doomed = [d.id for _, dupes in duplicated for d in dupes]
        if doomed:
            screening_store.delete_many(doomed)
    print_report(duplicated, len(screenings), args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
