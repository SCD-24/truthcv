"""The application-record workflows shared by the HTTP routes and MCP tools.

Only the parts that genuinely coincide between api/routes.py and
agenttools/tools_ledger.py live here, plus the export-bundle machinery and the
agent's application workflows. The export helpers are used by only the HTTP
route today, but they are entirely framework-free and belong with the rest of
the application-record logic rather than inline in a route module.

The agent's ``record_application``, ``get_approved_applications`` and
``report_apply_failure`` workflows also live here (``record_application``,
``get_approved_applications``, ``record_apply_failure``), so the MCP tools in
agenttools/tools_ledger.py are thin adapters. That includes the claim-lease
mechanics (``_CLAIM_LEASE_SECONDS`` and ``screening.store.claim_for_run``),
which only the agent uses, and the backfill and structured-evidence steps of
``record_application``, which deliberately do more than the HTTP create route.
The tool still merges its named parameters and parses the evidence before
calling in, so a malformed payload is rejected before any write.

What is deliberately NOT here:

* **FastAPI concerns.** Nothing here imports FastAPI: the ``StreamingResponse``
  that wraps ``build_export_zip``'s output stays in api/routes.py, and the
  export format (CSV column order, zip layout, per-company folder naming) is a
  user-facing contract that must stay byte-for-byte stable.
"""

from __future__ import annotations

from storage import data_dir

import agentconfig.store as _agentconfig_store
import applications as app_store
import applications.store as _apps_store
import coverletter.store as letter_store
import screening.store as screening_store
from companyresearch.store import open_contradictions
from screening.cooldown import cooldown
from identity.company import company_identity_key as _company_identity_key
from identity.url import normalize_application_url
from runs.derive import counters_by_run as _counters_by_run
from services.letters import (
    NO_FILE as _NO_LETTER_FILE,
    render_screening_letter as _render_screening_letter,
)
from services.runs import bump_counters as _bump_run_counters


def _matches(app, needle: str) -> bool:
    """True when ``needle`` (already lower-cased) is a substring of any of the
    record's company, website, application_url, notes, posting or role."""
    fields = [
        app.company or "",
        app.website or "",
        app.application_url or "",
        app.notes or "",
        app.posting or "",
        app.role or "",
    ]
    return any(needle in field.lower() for field in fields)


def filter_applications(apps: list, q: str = "") -> list:
    """Keep the records matching ``q`` case-insensitively; blank ``q`` keeps all.

    Shared by the whole-list and the paged readers so the two can never
    disagree about what a search term matches.
    """
    needle = q.strip().lower()
    if not needle:
        return list(apps)
    return [a for a in apps if _matches(a, needle)]


def list_applications(q: str = "") -> list:
    """Every tracked application, most recent first, optionally filtered by ``q``.

    The single source of the sort both the HTTP list route and the export route
    apply, so the two can never disagree about order. The export route calls
    this without ``q``, so export is never filtered.

    ``q`` is matched case-insensitively against the company, website,
    application_url, notes, posting, and role fields when non-blank.
    """
    apps = sorted(app_store.load_all(), key=lambda a: a.created_at, reverse=True)
    return filter_applications(apps, q)


def list_applications_page(
    limit: int, offset: int, sort: str, direction: str, q: str = ""
) -> tuple[list, int]:
    """One page of applications, sorted by the given key and direction.

    Args:
        limit: Maximum number of applications per page. If <= 0, returns all (unlimited).
        offset: Number of applications to skip from the start. Clamped to >= 0.
        sort: The sort column (e.g. "company", "date").
        direction: "asc" or "desc".
        q: Optional case-insensitive search (see ``filter_applications``). The
           filter runs before paging, so ``total`` is the number of matches and
           the pager reflects the search.

    Returns:
        A tuple of (page_of_applications, total_count).

    Raises:
        ValueError: If sort key or direction is invalid.
    """
    from applications.sorting import sort_applications

    all_apps = filter_applications(app_store.load_all(), q)
    sorted_apps = sort_applications(all_apps, sort=sort, direction=direction)
    total = len(sorted_apps)

    offset = max(0, offset)
    if offset >= total:
        return [], total

    if limit <= 0:
        return sorted_apps[offset:], total
    else:
        return sorted_apps[offset:offset + limit], total


def create_application_record(fields: dict):
    """Create an application record from already-validated editable ``fields``."""
    return app_store.create(fields)


def update_application_record(app_id: str, patch: dict):
    """Patch an application's editable fields; None when the id is unknown."""
    return app_store.update(app_id, patch)


_EXPORT_COLUMNS = (
    "company",
    "application_date",
    "website",
    "application_url",
    "submitted",
    "submission_type",
    "reached_out",
    "to_who",
    "response_received",
    "method",
    "notes",
    "posting",
    "documents",
)


def _app_document_files(app) -> list[str]:
    """Names of this application's rendered files that exist on the volume."""
    names = [*app_store.cv_filenames(app.id), *app_store.cover_letter_filenames(app.id)]
    return [n for n in names if (data_dir() / n).exists()]


def _app_csv_row(app) -> list[str]:
    """One CSV row: editable fields plus a summary of attached document files."""
    docs = "; ".join(_app_document_files(app))
    values = {f: getattr(app, f) for f in app.EDITABLE}
    values["documents"] = docs
    return [str(values.get(col, "")) for col in _EXPORT_COLUMNS]


def _safe_folder(name: str, fallback: str, used: set[str]) -> str:
    """A filesystem-safe, unique folder name for a company (fallback if empty)."""
    import re

    base = re.sub(r'[<>:"/\\|?*]+', "_", (name or "").strip()) or fallback
    candidate, n = base, 2
    while candidate in used:
        candidate, n = f"{base} ({n})", n + 1
    used.add(candidate)
    return candidate


def _write_csv(zf, apps) -> None:
    """Write applications.csv (header + one row per application) into the zip."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)
    for app in apps:
        writer.writerow(_app_csv_row(app))
    zf.writestr("applications.csv", buffer.getvalue())


def _write_documents(zf, apps) -> None:
    """Add each application's existing files under a per-company folder."""
    used: set[str] = set()
    for app in apps:
        files = _app_document_files(app)
        if not files:
            continue
        folder = _safe_folder(app.company, app.id, used)
        for name in files:
            zf.write(str(data_dir() / name), arcname=f"{folder}/{name}")


def build_export_zip(apps):
    """Build the export zip in memory and return a rewound BytesIO stream."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        _write_csv(zf, apps)
        _write_documents(zf, apps)
    buffer.seek(0)
    return buffer


def _is_submission(app) -> bool:
    """Whether a ledger row records an application that was actually sent.

    ``submitted`` is the field that means this, but it defaults to False on the
    dataclass and predates ``record_application`` naming it, so a row that was
    genuinely submitted can still carry False. Confirmation text is accepted as
    the corroborating evidence: nothing writes it but a captured confirmation.
    """
    return bool(app.submitted or app.confirmation.text.strip())


def gather_approvable_screenings() -> list[dict]:
    """Every operator-approved screening with its blocked-reason decision.

    This is the reusable read half of ``tools_ledger.get_approved_applications``:
    it combines the ledger, cover-letter, cooldown and company-research reads
    into the "why is this screening not currently approvable" cascade, and
    returns one entry per approved screening with its ``blocked_reason`` and the
    metadata the caller reports. It performs NO claiming and consumes no per-run
    cap — ``get_approved_applications`` below layers ``_CLAIM_LEASE_SECONDS``
    and ``claim_for_run`` on top of what this returns, because only the agent
    claims work.

    The blocked-reason cascade is ordered deliberately: ``already_applied`` and
    ``contradictory_research`` describe an item that must not go out at all, the
    others one that cannot go out yet. See the tool's docstring for the full
    rationale of each reason.

    Each entry carries the ``screening`` object itself so the caller can read
    its live ``claimed_by_run`` and apply its own lease logic.
    """
    applied_urls = {
        norm
        for a in app_store.load_all()
        if _is_submission(a)
        for norm in (normalize_application_url(a.application_url),)
        if norm
    }
    applied_screening_ids = {
        a.screening_id
        for a in app_store.load_all()
        if _is_submission(a) and a.screening_id
    }

    results = []
    for s in screening_store.load_all():
        if s.approval != "approved":
            continue
        draft = letter_store.load(s.id)
        status = cooldown(s.company, s.role or None)
        contradictions = [
            {"claim": g["claim"], "findings": [f.to_dict() for f in g["findings"]]}
            for g in open_contradictions(s.company)
        ]
        # already_applied and contradictory_research outrank the rest: those
        # two describe an item that must not go out at all, the others one
        # that cannot go out yet.
        if s.id in applied_screening_ids or (s.url and normalize_application_url(s.url) in applied_urls):
            blocked_reason = "already_applied"
        elif contradictions:
            blocked_reason = "contradictory_research"
        elif status.blocked:
            blocked_reason = "cooldown"
        elif s.apply_blocker == "login_required":
            blocked_reason = "login_required"
        elif not s.url.strip():
            blocked_reason = "no_url"
        else:
            blocked_reason = ""

        results.append(
            {
                "screening": s,
                "blocked_reason": blocked_reason,
                "contradictions": contradictions,
                "cover_letter": draft.text if draft else "",
                "letter_source": draft.source if draft else "",
            }
        )
    return results


def _backfill_from_screening(fields: dict, screening_id: str) -> dict:
    """Fill identity fields the caller left absent or empty from the screening.

    An application recorded against an approved queue item should carry that
    item's company, role, URL and posting so the Applications row is populated
    without the agent having to repeat them. Caller-supplied non-empty values
    always win; an unknown ``screening_id`` changes nothing (the caller's
    fields stand, exactly as before this backfill existed).
    """
    if not screening_id:
        return fields
    s = screening_store.get(screening_id)
    if s is None:
        return fields
    inherited = {
        "company": s.company,
        "role": s.role,
        "application_url": s.url,
        "posting": s.posting_text,
    }
    for key, value in inherited.items():
        if not fields.get(key):
            fields[key] = value
    return fields


def record_application(
    fields: dict,
    screening_id: str = "",
    run_id: str = "",
    *,
    fields_submitted: list | None = None,
    confirmation=None,
    screening=None,
    attachments: list | None = None,
):
    """Write one submitted application and its evidence; return ``(app, created)``.

    This is the agent's ``record_application`` workflow minus its input
    handling: the tool merges its named parameters into ``fields`` and parses
    the structured evidence into model objects (``FieldSubmitted``,
    ``Confirmation``, ``Screening``, ``Attachment``) BEFORE calling this, so a
    malformed payload is rejected before any store write happens here — the
    orphan-row fix. Each evidence argument is ``None`` when not provided.

    ``applications.store.create`` only accepts ``Application.EDITABLE`` fields,
    so the editable record is created (or, for a ``screening_id`` that already
    has a row, patched) first, and each structured field is then persisted
    through its own ``save_*`` helper in ``applications.store``. With a
    ``screening_id`` the approved queue item is retired, and an application
    for an item this ``run_id`` did not hold is counted as an over-cap write.
    """
    backfilled = _backfill_from_screening(fields, screening_id)
    if screening_id:
        app, created = _apps_store.create_for_screening(backfilled, screening_id)
        if not created:
            # A retry against an existing row: apply the caller's editable
            # fields so the re-record improves the record instead of being
            # silently dropped. Use `fields`, not `backfilled`, so inherited
            # values the caller did not actually send are not reintroduced.
            app = update_application_record(app.id, fields) or app
    else:
        app = create_application_record(backfilled)
        created = True

    if fields_submitted is not None:
        app = _apps_store.save_fields_submitted(app.id, fields_submitted) or app
    if confirmation is not None:
        app = _apps_store.save_confirmation(app.id, confirmation) or app
    if screening is not None:
        app = _apps_store.save_screening(app.id, screening) or app
    if attachments is not None:
        app = _apps_store.save_attachments(app.id, attachments) or app

    # An approved queue item retires on evidence of a confirmed application,
    # not on the agent electing to retire it.
    if screening_id:
        # Read the claim before mark_applied clears it, so a submission for an
        # item this run did not hold can be flagged. Best-effort throughout:
        # the ledger write above already happened, so nothing here may raise
        # or change the return shape — a real submission must never be lost
        # over an accounting failure.
        # applications_submitted is NOT bumped here: it is derived on read from
        # the application records themselves (runs/derive.py), and bumping it
        # too would double-count. over_cap_writes stays an incremented counter
        # because it records a lease violation with no derivable source.
        if run_id:
            try:
                held = screening_store.get(screening_id)
                over_cap = bool(held) and held.claimed_by_run != run_id
                if over_cap:
                    _bump_run_counters(run_id, over_cap_writes=1)
            except Exception:
                pass
        screening_store.mark_applied(screening_id)

    return app, created


# How long a hand-out claim holds before another run may reclaim the item —
# long enough to cover one application's browser interaction, short enough
# that a crashed run's work comes back reasonably soon.
_CLAIM_LEASE_SECONDS = 900


def _already_submitted_this_run(run_id: str) -> int:
    """How many applications this run has already submitted, so a repeated
    ``get_approved_applications`` call within the same run counts them
    against the per-run cap instead of resetting it every call.

    A submitted item has already left the approved queue (it is not one of
    the items the loop below re-claims), so this must be seeded separately
    rather than double counted with the loop's own claimed_count. Reuses
    ``runs.derive.counters_by_run`` over the applications store alone
    (``screenings=[]``, since only ``applications_submitted`` is wanted).
    Best-effort: any error here must not block the tool, so it falls back
    to 0.
    """
    try:
        applications = _apps_store.load_all()
        counters = _counters_by_run([run_id], [], applications)
        return counters[run_id]["applications_submitted"]
    except Exception:
        return 0


def get_approved_applications(run_id: str = "", limit: int = 0) -> list[dict]:
    """The approved items a run should apply to, claimed for ``run_id`` up to its cap.

    The workflow behind the agent's ``get_approved_applications`` tool, whose
    docstring states the full contract: per-run cap (``limit``, else
    ``maxApplicationsPerRun``), the claim-lease, the blocked-reason guards, and
    the rendered cover-letter file for an item that is actually going out. It
    lives here so the tool is a thin adapter over it.
    """
    cap = 0
    if limit and limit > 0:
        cap = limit
    else:
        cfg = _agentconfig_store.load()
        cap = getattr(cfg, "max_applications_per_run", None) or 0

    # The reusable reads and the blocked-reason cascade live in
    # gather_approvable_screenings; the per-run cap and the claim-lease below
    # are agent-only, since only the agent claims work.
    items = []
    claimed_count = _already_submitted_this_run(run_id) if run_id else 0
    for entry in gather_approvable_screenings():
        s = entry["screening"]
        blocked_reason = entry["blocked_reason"]

        claimed_by_run = s.claimed_by_run
        if not blocked_reason and run_id:
            if cap and claimed_count >= cap:
                continue  # over this run's cap: leave it for a later run
            claimed = screening_store.claim_for_run(s.id, run_id, _CLAIM_LEASE_SECONDS)
            if claimed is None:
                continue  # lost a race for this item; skip rather than misreport it
            claimed_by_run = claimed.claimed_by_run
            claimed_count += 1
        elif not blocked_reason and cap and claimed_count >= cap:
            continue
        elif not blocked_reason:
            claimed_count += 1

        # Only an item that is actually going out gets a file rendered for it:
        # a blocked item is reported, never applied to, so rendering it would
        # buy nothing and cost a WeasyPrint pass per blocked item per run.
        letter_file = (
            _render_screening_letter(s.id, entry["cover_letter"])
            if not blocked_reason
            else dict(_NO_LETTER_FILE)
        )

        items.append(
            {
                "screening_id": s.id,
                "company": s.company,
                "role": s.role,
                "url": s.url,
                "attempts": s.apply_attempts,
                "blocked_reason": blocked_reason,
                "contradictions": entry["contradictions"],
                "cover_letter": entry["cover_letter"],
                "letter_source": entry["letter_source"],
                "cover_letter_asset_id": letter_file["asset_id"],
                "cover_letter_path": letter_file["path"],
                "cover_letter_download_url": letter_file["download_url"],
                "claimed_by_run": claimed_by_run,
            }
        )
    return items


def record_apply_failure(
    screening_id: str,
    error: str,
    blocker: str = "",
    signin_url: str = "",
):
    """Record a failed apply attempt on an approved item; the updated screening or None.

    Exists so the agent's ``report_apply_failure`` tool reaches the screening
    store through this layer like the rest of the approved-queue workflow. The
    item stays approved and queued (retry-on-next-run); ``None`` means the
    ``screening_id`` is unknown.
    """
    return screening_store.record_apply_failure(
        screening_id, error, blocker=blocker, signin_url=signin_url
    )


def resolve_alias_company(company: str) -> str:
    """Resolve the company string ``get_profile_answers`` should alias against.

    If an application row already exists whose company matches ``company``'s
    identity key, that row's stored ``company`` string is returned (the
    earliest-created one wins, when several match) so the alias stays frozen
    to the address already submitted to that employer. Otherwise the
    identity key itself is returned, so a brand-new company is aliased from
    its normalized slug rather than its raw, possibly differently-cased or
    -suffixed, spelling. Never raises: a blank/non-str ``company``, or a
    failure to load the applications store, falls back to ``company``
    unchanged (aliasing degrades to today's plain per-call transform).

    Public so the ``get_profile_answers`` tool stays a thin adapter; the
    applications store is read through module-attribute access at call time.
    """
    if not isinstance(company, str) or not company.strip():
        return company
    target_key = _company_identity_key(company)
    if not target_key:
        return company
    try:
        rows = _apps_store.load_all()
    except Exception:
        return company
    candidates = [
        row
        for row in rows
        if isinstance(row.company, str) and _company_identity_key(row.company) == target_key
    ]
    if not candidates:
        return target_key
    earliest = min(candidates, key=lambda row: row.created_at or "")
    return earliest.company
