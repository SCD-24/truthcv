"""The application-record workflows shared by the HTTP routes and MCP tools.

Only the parts that genuinely coincide between api/routes.py and
agenttools/tools_ledger.py live here, plus the export-bundle machinery. The
export helpers are used by only the HTTP route today, but they are entirely
framework-free and belong with the rest of the application-record logic rather
than inline in a route module.

What is deliberately NOT here:

* **The claim-lease mechanics** of ``tools_ledger.get_approved_applications``
  (``_CLAIM_LEASE_SECONDS`` and ``screening.store.claim_for_run``). Only the
  agent claims work, so leasing stays on the MCP side. This module supplies the
  reusable reads and the "why is this screening not currently approvable"
  decision (``gather_approvable_screenings``); the tool layers its per-run cap
  and claim-lease on top of what that returns.
* **The structured-evidence and backfill steps** of ``record_application``.
  That tool deliberately does more than the HTTP create route — backfilling
  from an approved queue item and persisting attachments/confirmation/screening
  through their own ``save_*`` helpers. Only its terminal store write is
  shared, through ``create_application_record`` / ``update_application_record``.
* **FastAPI concerns.** Nothing here imports FastAPI: the ``StreamingResponse``
  that wraps ``build_export_zip``'s output stays in api/routes.py, and the
  export format (CSV column order, zip layout, per-company folder naming) is a
  user-facing contract that must stay byte-for-byte stable.
"""

from __future__ import annotations

from storage import data_dir

import applications as app_store
import coverletter.store as letter_store
import screening.store as screening_store
from companyresearch.store import open_contradictions
from screening.cooldown import cooldown
from screening.url import normalize_application_url


def list_applications() -> list:
    """Every tracked application, most recent first.

    The single source of the sort both the HTTP list route and the export route
    apply, so the two can never disagree about order.
    """
    return sorted(app_store.load_all(), key=lambda a: a.created_at, reverse=True)


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
    cap — the agent tool layers ``_CLAIM_LEASE_SECONDS`` and ``claim_for_run``
    on top of what this returns, because only the agent claims work.

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
