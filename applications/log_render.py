"""Render APPLICATION_LOG.md — the ledger's plain-text projection.

Ported from the retired Jobs repo's ``appreview/render.py`` so the decision
that a readable log survives outside the application is honoured after that
repo is deleted. Two things came across deliberately:

* ``render_log`` is pure — applications in, Markdown out, no other input.
* ``write_log`` refuses to replace an existing log unless every application
  is accounted for in the new text exactly once (``RenderRefused``).

The guard is the point. In Jobs the agent read the rendered file to enforce
cooldowns, so a record silently missing from the log was a company the agent
would re-apply to. TruthCV now serves cooldowns from the screening store
instead, but the same integrity property is what makes the log trustworthy as
a standalone account: if it exists, it accounts for the whole ledger.

Unlike the Jobs original this renders EVERY application, not only the
agent-submitted ones. The ledger is now one population — rendering a subset
would drop 22 of 33 rows and reintroduce exactly the silent-omission failure
the completeness guard exists to prevent.

Note that the guard only covers what it is HANDED. Loading the ledger is the
caller's job, and `store.load_all()` deliberately fails safe to an empty list,
which this guard would find perfectly complete. `scripts/render_application_log.py`
checks the ledger loaded whole before calling in here; any other caller must
do the same.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .model import Application

HEADER = """# Application log

GENERATED FILE — do not edit by hand. Rendered from the application ledger
(`applications.json` on the data volume) by `scripts/render_application_log.py`.
Edit the application and re-render.

Every application TruthCV tracks appears below exactly once. Entries marked
`reconstructed` were rebuilt from the hand-written log rather than observed at
submit time; entries marked `observed` were captured as the submission
happened.
"""


class RenderRefused(Exception):
    """Raised when the rendered log does not account for every application."""


# Order in which screening verdicts are rendered, so the log is diff-friendly
# rather than dependent on field declaration order.
_SCREENING_ORDER = ("entity", "remote", "salary", "language", "role_type")

_MARKER = "<!-- record: {} -->"


def _humanize_key(key: str) -> str:
    """``role_type`` -> ``Role type``."""
    return key.replace("_", " ").capitalize()


def _cell(value: object) -> str:
    """Make a value safe to render: table-safe, and unable to forge a marker.

    Escaping the comment opener matters more than it looks. The completeness
    guard counts marker occurrences, so a note or a submitted field value
    containing the literal marker text would inflate the count for its own
    record — refusing every future write of the log — or supply a marker for a
    record the renderer had actually dropped, which is the exact failure the
    guard exists to catch. Content can therefore never open an HTML comment.
    """
    text = " ".join(str(value).split())
    return text.replace("<!--", "&lt;!--").replace("|", "\\|")


def _glassdoor_line(glassdoor) -> str | None:
    """The Glassdoor check as one bullet, or None when nothing was recorded."""
    if glassdoor.rating not in ("", None):
        suffix = f" ({glassdoor.reviews} reviews)" if glassdoor.reviews not in ("", None) else ""
        waiver = " — waiver applied" if glassdoor.waiver_applied else ""
        return f"- **Glassdoor:** {_cell(glassdoor.rating)}{suffix}{waiver}"
    if glassdoor.note:
        return f"- **Glassdoor:** {_cell(glassdoor.note)}"
    return None


def _status_line(app: Application) -> str:
    """The headline disposition, in whichever vocabulary the record uses.

    Migrated Jobs records carry ``confirmed``/``pending``; records created in
    TruthCV carry the tracker's own statuses (``Applied``, ``Rejected``, ...).
    Both are rendered without translating one into the other, and a record is
    only ever called *confirmed* when its own status says so.
    """
    status = (app.status or "").strip()
    if status == "confirmed":
        text = _cell(app.confirmation.text or "")
        return f'SUBMITTED — confirmed ("{text}")' if text else "SUBMITTED — confirmed"
    if status == "pending":
        return "PENDING — submitted but confirmation was not read"
    submission = "submitted" if app.submitted else "not submitted"
    return f"{_cell(status).upper()} — {submission}" if status else submission.upper()


def _provenance_lines(app: Application) -> list[str]:
    """Capture method and any confirmation evidence not already in the status."""
    lines = []
    if app.capture_method == "reconstructed":
        lines.append(
            "- **Provenance:** reconstructed from the hand-written log, "
            "not observed at submit time"
        )
    elif app.capture_method == "observed":
        lines.append("- **Provenance:** observed at submit time")
    text = (app.confirmation.text or "").strip()
    if text and app.status != "confirmed":
        lines.append(f'- **Confirmation:** "{_cell(text)}"')
    return lines


def _screening_lines(app: Application) -> list[str]:
    """One bullet per recorded screening verdict, in a stable order."""
    lines = []
    for key in _SCREENING_ORDER:
        value = getattr(app.screening, key, "")
        if value:
            lines.append(f"- **{_humanize_key(key)}:** {_cell(value)}")
    glassdoor = _glassdoor_line(app.screening.glassdoor)
    if glassdoor:
        lines.append(glassdoor)
    return lines


def _fields_table(app: Application) -> list[str]:
    """The submitted form fields as a Markdown table with their provenance."""
    if not app.fields_submitted:
        return []
    rows = ["\n**Fields submitted:**\n", "| Field | Value | Source |", "|---|---|---|"]
    rows += [
        f"| {_cell(f.label)} | {_cell(f.value)} | {_cell(f.source)} |"
        for f in app.fields_submitted
    ]
    return rows


def _notes_lines(app: Application) -> list[str]:
    """Notes as bullets.

    ``Application.notes`` is a single string; migrated records hold several
    notes joined as blank-line-separated paragraphs, so splitting on the blank
    line restores the separate notes the Jobs log rendered individually.
    """
    paragraphs = [p.strip() for p in (app.notes or "").split("\n\n") if p.strip()]
    if not paragraphs:
        return []
    return ["\n**Notes:**\n"] + [f"- {_cell(p)}" for p in paragraphs]


def _section(number: int, app: Application) -> list[str]:
    """One application's complete section, marker included."""
    role = _cell(app.role) or "role not recorded"
    parts = [
        f"\n---\n\n## {number}. {_cell(app.company)} — {role}",
        _MARKER.format(app.id),
        f"- **Status:** {_status_line(app)}",
        f"- **Date:** {_cell(app.application_date) or 'not recorded'}",
        f"- **URL:** {_cell(app.application_url) or 'not recorded'}",
    ]
    if app.ats:
        parts.append(f"- **ATS:** {_cell(app.ats)}")
    parts += _provenance_lines(app)
    parts += _screening_lines(app)
    if app.attachments:
        parts.append("- **Attachments:** " + ", ".join(_cell(a.path) for a in app.attachments))
    parts += _fields_table(app)
    if app.gaps_disclosed:
        parts.append("\n**Gaps disclosed:**\n")
        parts += [f"- {_cell(gap)}" for gap in app.gaps_disclosed]
    parts += _notes_lines(app)
    parts.append("")
    return parts


def render_log(applications: list[Application]) -> str:
    """Render the whole ledger to Markdown. Pure: applications in, text out."""
    ordered = sorted(applications, key=lambda a: (a.application_date or "", a.id))
    parts = [HEADER]
    for number, app in enumerate(ordered, start=1):
        parts += _section(number, app)
    return "\n".join(parts) + "\n"


def _unaccounted(rendered: str, ids: list[str]) -> list[str]:
    """Ids whose marker does not appear in the rendered text exactly once.

    Counting rather than testing membership is what makes the guard hold: two
    applications sharing an id render one section each carrying the same
    marker, so a membership test is satisfied by the survivor while the other
    is dropped from the log without complaint.
    """
    return [i for i in ids if rendered.count(_MARKER.format(i)) != 1]


def write_log(applications: list[Application], target_path: str | Path) -> Path:
    """Render and atomically replace ``target_path``.

    Refuses (``RenderRefused``) if the applications do not have unique ids, or
    if any application's marker does not appear in the rendered text exactly
    once. Writes to a temp file on the same directory and renames, so the log
    is never left half-written and a reader never sees a partial account.
    """
    target_path = Path(target_path)
    ids = [a.id for a in applications]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise RenderRefused(
            "applications do not have unique ids: " + ", ".join(duplicates)
        )

    rendered = render_log(applications)
    unaccounted = _unaccounted(rendered, ids)
    if unaccounted:
        raise RenderRefused(
            "rendered log does not account for applications exactly once: "
            + ", ".join(unaccounted)
        )

    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=target_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(rendered)
        os.replace(temp_name, target_path)
    except BaseException:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
        raise
    # mkstemp creates 0600 and os.replace preserves it, which would leave the
    # log unreadable to the human it exists for — the whole point of keeping a
    # plain-text account outside the application. 0644 matches every other file
    # already on the data volume (applications.json, answers.yaml and the
    # rendered documents are all 0644 root-owned), so this follows the volume's
    # existing posture rather than making the log a special case. That posture
    # is worth revisiting, but tightening only this file while the ledger it is
    # rendered from sits beside it at 0644 would buy nothing.
    os.chmod(target_path, 0o644)
    return target_path
