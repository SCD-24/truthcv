"""Merge duplicate Application rows left by a retried ``record_application``.

The incident this repairs: while recording a single submission (the RobCo one),
an agent retried the ``record_application`` MCP tool roughly four times within a
couple of minutes — one of those calls failed partway through with a tooling
error — and each attempt minted a *separate* Application row. The result was
four rows on the volume for what is really one application to one company, their
evidence scattered across the copies (one carried the confirmation, another the
as-submitted fields, and so on). This one-off maintenance script folds each such
cluster back into a single row without losing any of that evidence.

Grouping. Rows are bucketed so that only genuine duplicates of one submission
land together:

* Any row carrying a non-empty ``screening_id`` is bucketed by that id — it is
  the dedupe key the store already uses, so rows sharing it are by construction
  the same screening's application.
* A row *without* a ``screening_id`` is bucketed by
  ``(company lowercased, normalize_application_url(application_url))`` — but only
  if it "looks like a real submission" (``submitted`` is True or its
  ``confirmation`` carries any text/evidence) and only if its normalized URL is
  non-empty. Rows that are neither submitted nor confirmed, and rows whose URL
  normalizes to nothing, never group with anything by URL: they are left
  strictly alone.
* A bucket holding a single row is UNCHANGED — never reported as a merge.
* A bucket holding two or more rows is a mergeable GROUP.

Merge rules for a group. The CANONICAL row is the earliest by ``created_at``
(ISO-8601 string order; empty timestamps and ties fall back to first-in-list).
The other rows are folded into it:

* Simple scalar fields (company, role, application_url, posting, ats, method,
  status, submission_type, capture_method, profile, application_date) take the
  canonical row's value when it is non-empty, otherwise the first non-empty
  value from the other rows in group order.
* Structured evidence (fields_submitted, confirmation, screening, attachments,
  gaps_disclosed) takes the "richest" populated value across the whole group:
  the canonical's own value when it is populated, otherwise the first populated
  value found in group order. Two populated values are never merged into one —
  one is picked.
* ``notes`` concatenates every DISTINCT non-empty note across the group, in
  original row order, each as its own ``\n\n``-separated paragraph.

Safety. Before deleting the non-canonical rows, each is checked for an owned
``cv_document`` or ``cover_letter_document``: ``applications.store.delete`` also
unlinks a row's rendered files, so deleting a row that owns one would destroy
evidence. Such rows are NOT deleted — they are reported as MANUAL-REPAIR for the
operator to reconcile by hand. Only non-canonical rows owning neither document
are deleted.

This script goes through ``applications.store`` for every read and write; it
never touches ``data/applications.json`` directly. It is idempotent: once the
merge has run, each cluster's non-canonical rows are gone (or held back as
manual-repair), so a second ``--apply`` finds only singleton buckets — or a
``screening_id`` that no longer repeats — and merges nothing. The default is a
dry run that writes nothing and only reports.

Usage::

    python scripts/repair_duplicate_applications.py           # dry run, report only
    python scripts/repair_duplicate_applications.py --apply    # merge duplicates
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple

# Run as ``python scripts/repair_duplicate_applications.py`` and Python puts
# scripts/ on the path rather than the repo root, so the packages below would
# not resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import applications.store as applications_store  # noqa: E402
from applications.model import Application  # noqa: E402
from screening.url import normalize_application_url  # noqa: E402


# --- "populated" / "non-empty" helpers ----------------------------------------

def _nonempty(value) -> bool:
    """True if ``value`` carries real content (blank/whitespace strings do not)."""
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict)):
        return bool(value)
    return bool(value)


def _confirmation_populated(confirmation) -> bool:
    """True if any Confirmation field holds a non-empty string."""
    return any(
        _nonempty(getattr(confirmation, f))
        for f in ("text", "confirmed_at", "evidence")
    )


def _screening_populated(screening) -> bool:
    """True if any Screening field is set, including the nested Glassdoor check."""
    if any(
        _nonempty(getattr(screening, f))
        for f in ("entity", "remote", "salary", "language", "role_type")
    ):
        return True
    g = screening.glassdoor
    return any(
        _nonempty(getattr(g, f))
        for f in ("rating", "reviews", "waiver_applied", "note")
    )


def _looks_like_submission(app: Application) -> bool:
    """True if the row is a genuine submission (submitted, or has confirmation)."""
    return bool(app.submitted) or _confirmation_populated(app.confirmation)


# --- Grouping ------------------------------------------------------------------

def _bucket_key(app: Application):
    """The grouping key for ``app``, or None if it does not participate.

    A non-empty ``screening_id`` keys on that id. Otherwise the row keys on
    ``(company lowercased, normalized url)`` — but only when it looks like a
    real submission and its URL normalizes to something non-empty; anything else
    is left ungrouped (returns None).
    """
    sid = (app.screening_id or "").strip()
    if sid:
        return ("screening_id", sid)
    if not _looks_like_submission(app):
        return None
    norm = normalize_application_url(app.application_url)
    if not norm:
        return None
    return ("company_url", ((app.company or "").strip().lower(), norm))


def group_duplicates(apps: list[Application]) -> list[tuple[tuple, list[Application]]]:
    """Bucket applications by key, preserving first-seen order within each bucket.

    Returns ``(key, rows)`` pairs for every bucket (singletons included, so the
    caller can count UNCHANGED rows). Rows whose key is None never participate.
    """
    buckets: dict = {}
    order: list = []
    for app in apps:
        key = _bucket_key(app)
        if key is None:
            continue
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(app)
    return [(key, buckets[key]) for key in order]


def classify(
    apps: list[Application],
) -> tuple[list[Application], list[tuple[tuple, list[Application]]]]:
    """Split buckets into (unchanged singleton rows, mergeable 2+ groups)."""
    unchanged: list[Application] = []
    groups: list[tuple[tuple, list[Application]]] = []
    for key, bucket in group_duplicates(apps):
        if len(bucket) == 1:
            unchanged.extend(bucket)
        else:
            groups.append((key, bucket))
    return unchanged, groups


# --- Merge ---------------------------------------------------------------------

# Scalar fields whose merged value is written through ``store.update`` in one
# call. ``notes`` and ``gaps_disclosed`` are handled specially and appended to
# the same patch (there is no dedicated store setter for either).
_SCALAR_FIELDS = (
    "company",
    "role",
    "application_url",
    "posting",
    "ats",
    "method",
    "status",
    "submission_type",
    "capture_method",
    "profile",
    "application_date",
)


class MergePlan(NamedTuple):
    """A computed merge for one group: what to write and what to remove.

    A tuple, so ``canonical``/``deleted_ids``/``manual_repair_ids`` read as the
    brief's ``(canonical, deleted_ids, manual_repair_ids)`` while the merged
    values needed to actually write the change ride along.
    """

    key: tuple
    canonical: Application
    deleted_ids: list[str]
    manual_repair_ids: list[str]
    patch: dict
    fields_submitted: list
    confirmation: object
    screening: object
    attachments: list


def _pick_canonical(bucket: list[Application]) -> Application:
    """The earliest row by ``created_at``; empties and ties fall to first-in-list."""

    def sort_key(indexed):
        idx, app = indexed
        created = app.created_at or ""
        # Empty timestamps sort last so a real timestamp wins; idx keeps ties
        # (and all-empty buckets) in original order.
        return (created == "", created, idx)

    return min(enumerate(bucket), key=sort_key)[1]


def _pick_scalar(canonical: Application, others: list[Application], attr: str):
    """Canonical's value if non-empty, else the first non-empty from ``others``."""
    value = getattr(canonical, attr)
    if _nonempty(value):
        return value
    for other in others:
        candidate = getattr(other, attr)
        if _nonempty(candidate):
            return candidate
    return value


def _pick_evidence(canonical: Application, bucket: list[Application], attr, populated):
    """Richest populated value: canonical's if populated, else first in group order."""
    can_value = getattr(canonical, attr)
    if populated(can_value):
        return can_value
    for app in bucket:
        candidate = getattr(app, attr)
        if populated(candidate):
            return candidate
    return can_value


def _merge_notes(bucket: list[Application]) -> str:
    """Distinct non-empty notes across the group, in row order, as paragraphs."""
    seen: set[str] = set()
    out: list[str] = []
    for app in bucket:
        note = (app.notes or "").strip()
        if note and note not in seen:
            seen.add(note)
            out.append(note)
    return "\n\n".join(out)


def merge_group(key: tuple, bucket: list[Application]) -> MergePlan:
    """Compute the merge for one 2+ group without writing anything.

    Picks the canonical row, folds scalar and structured-evidence fields onto
    it, and partitions the non-canonical rows into those safe to delete and
    those held back for manual repair (they own a rendered document).
    """
    canonical = _pick_canonical(bucket)
    others = [a for a in bucket if a is not canonical]

    patch = {attr: _pick_scalar(canonical, others, attr) for attr in _SCALAR_FIELDS}
    patch["notes"] = _merge_notes(bucket)
    # gaps_disclosed is an EDITABLE field with no dedicated store setter, so its
    # merged (richest) value rides in the same update patch as the scalars.
    patch["gaps_disclosed"] = _pick_evidence(
        canonical, bucket, "gaps_disclosed", _nonempty
    )

    fields_submitted = _pick_evidence(
        canonical, bucket, "fields_submitted", lambda v: bool(v)
    )
    confirmation = _pick_evidence(
        canonical, bucket, "confirmation", _confirmation_populated
    )
    screening = _pick_evidence(canonical, bucket, "screening", _screening_populated)
    attachments = _pick_evidence(canonical, bucket, "attachments", lambda v: bool(v))

    deleted_ids: list[str] = []
    manual_repair_ids: list[str] = []
    for other in others:
        if other.cv_document is not None or other.cover_letter_document is not None:
            # store.delete would also unlink this row's rendered files, so never
            # delete it automatically — surface it for the operator instead.
            manual_repair_ids.append(other.id)
        else:
            deleted_ids.append(other.id)

    return MergePlan(
        key=key,
        canonical=canonical,
        deleted_ids=deleted_ids,
        manual_repair_ids=manual_repair_ids,
        patch=patch,
        fields_submitted=fields_submitted,
        confirmation=confirmation,
        screening=screening,
        attachments=attachments,
    )


def plan_merges(groups: list[tuple[tuple, list[Application]]]) -> list[MergePlan]:
    """Compute a MergePlan for every mergeable group."""
    return [merge_group(key, bucket) for key, bucket in groups]


def apply_merges(plans: list[MergePlan]) -> None:
    """Write each plan's merged evidence and scalars, then delete safe duplicates.

    Evidence goes through the dedicated ``save_*`` setters and the scalars
    through a single ``update`` call, both against the canonical row's id, before
    any non-canonical row is removed. Manual-repair rows are left in place.
    """
    for plan in plans:
        cid = plan.canonical.id
        applications_store.save_fields_submitted(cid, plan.fields_submitted)
        applications_store.save_confirmation(cid, plan.confirmation)
        applications_store.save_screening(cid, plan.screening)
        applications_store.save_attachments(cid, plan.attachments)
        applications_store.update(cid, plan.patch)
        for app_id in plan.deleted_ids:
            applications_store.delete(app_id)


# --- Reporting -----------------------------------------------------------------

def _key_label(key: tuple) -> str:
    """Human-readable bucket key: the screening_id or the (company, url) tuple."""
    kind, value = key
    if kind == "screening_id":
        return f"screening_id={value!r}"
    company, norm = value
    return f"(company={company!r}, url={norm!r})"


def print_report(
    unchanged: list[Application], plans: list[MergePlan], applied: bool
) -> None:
    """Print the per-group merges and the UNCHANGED/MERGED/MANUAL-REPAIR counts."""
    merged_groups = [p for p in plans if p.deleted_ids]
    deleted_count = sum(len(p.deleted_ids) for p in plans)
    manual_ids = [mid for p in plans for mid in p.manual_repair_ids]

    print("dry run (nothing written)" if not applied else "applied changes")
    print(f"unchanged: {len(unchanged)}")
    print(f"merged: {len(merged_groups)} group(s), {deleted_count} duplicate row(s)")
    print(f"manual-repair: {len(manual_ids)} row(s)")

    for plan in plans:
        print(f"  group {_key_label(plan.key)}")
        print(f"    canonical: {plan.canonical.id}")
        if plan.deleted_ids:
            print(f"    merged and deleted: {', '.join(plan.deleted_ids)}")
        if plan.manual_repair_ids:
            print(
                "    manual-repair (owns a document, not deleted): "
                f"{', '.join(plan.manual_repair_ids)}"
            )

    if manual_ids:
        print(
            "Manual-repair rows own rendered documents; reconcile them by hand "
            "so their files are not lost."
        )


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="merge duplicates; default is a dry run that writes nothing",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load applications, classify, optionally apply merges, and print the report."""
    args = _parse_args(argv)
    unchanged, groups = classify(applications_store.load_all())
    plans = plan_merges(groups)
    if args.apply:
        apply_merges(plans)
    print_report(unchanged, plans, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
