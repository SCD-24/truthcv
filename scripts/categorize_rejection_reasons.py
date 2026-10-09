"""Normalize the ``failing_criterion`` of rejected screenings to canonical keys.

Older screening records carry free-text criteria ("1. Fully remote"). This
one-off maintenance script rewrites each rejected record's value to one of the
canonical rejection categories (see ``screening.rejection_categories``)
through ``screening.store.update``, and reports how many records are
unchanged, how many would change, the count per final category, and up to 50
distinct raw values that fell into ``other``. Non-rejected records are skipped.

It is idempotent: after ``--apply`` every value is canonical, so a second run
changes nothing. The default is a dry run. It never touches
``data/screenings.json`` directly.

Usage::

    python scripts/categorize_rejection_reasons.py           # dry run
    python scripts/categorize_rejection_reasons.py --apply   # write fixes
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

# Add the repo root so the packages below resolve when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402
from screening.rejection_categories import normalize_failing_criterion  # noqa: E402

MAX_OTHER_SHOWN = 50


def _is_rejected(s) -> bool:
    """True when the screening's verdict is 'rejected'."""
    return (s.verdict or "").strip().casefold() == "rejected"


def classify(screenings: list) -> tuple[list, list, int]:
    """Split screenings into (unchanged, to_normalize, skipped_count).

    Only rejected records are considered; ``to_normalize`` holds
    ``(screening, normalized)`` pairs whose raw stored value (possibly None)
    differs from its normalized form.
    """
    unchanged, fixable, skipped = [], [], 0
    for s in screenings:
        if not _is_rejected(s):
            skipped += 1
            continue
        normalized = normalize_failing_criterion(s.failing_criterion)
        if normalized != s.failing_criterion:
            fixable.append((s, normalized))
        else:
            unchanged.append(s)
    return unchanged, fixable, skipped


def apply_fixes(fixable: list) -> None:
    """Write each normalized failing_criterion through the store."""
    for s, normalized in fixable:
        screening_store.update(s.id, {"failing_criterion": normalized})


def print_report(
    unchanged: list, fixable: list, applied: bool, skipped: int = 0
) -> None:
    """Print counts, per-category counts and the raw values mapped to other."""
    print("applied changes" if applied else "dry run (nothing written)")
    print(f"skipped (not rejected): {skipped}")
    print(f"unchanged: {len(unchanged)}")
    print(f"to-normalize: {len(fixable)}")
    finals = Counter(s.failing_criterion for s in unchanged)
    finals.update(n for _, n in fixable)
    for category, n in sorted(finals.items()):
        print(f"  {category}: {n}")
    others = Counter(s.failing_criterion for s, n in fixable if n == "other")
    print(f"raw values mapped to 'other' ({len(others)} distinct):")
    for raw, n in others.most_common(MAX_OTHER_SHOWN):
        print(f"  {n} | {raw}")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write normalized values; default is a dry run",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, classify, optionally apply fixes, and report."""
    args = _parse_args(argv)
    unchanged, fixable, skipped = classify(screening_store.load_all())
    if args.apply:
        apply_fixes(fixable)
    print_report(unchanged, fixable, args.apply, skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
