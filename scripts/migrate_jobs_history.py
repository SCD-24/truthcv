"""One-time import of the retired Jobs repo's history into the TruthCV volume.

The Jobs repo kept its application history outside git (``applications/`` is
gitignored there because the records carry the user's phone number and home
address), so this data exists in exactly one place on disk. Nothing recreates
it. That shapes every choice here:

* The importer **never rewrites or removes an existing application**. It only
  appends, and it refuses to run at all if the current ``applications.json``
  exists but does not parse -- ``applications.store.load_all`` deliberately
  fails safe by returning ``[]`` on a malformed file, and a blind write on top
  of that empty list would destroy the records already on the volume.
* It is **idempotent**: a record is matched to an already-imported row by the
  natural key (company, role, application_date), so a second run adds nothing.
* It takes a **timestamped backup** of every file it is about to change before
  changing it.

It also writes ``jobs_migration_manifest.json`` onto the volume recording what
was imported and from where, so the retirement of the Jobs tree can be checked
against evidence rather than trust.

Screening history is imported from ``applications/SCREENING_LOG.md`` -- a
hand-written narrative, so the parse is deliberately conservative (see
``parse_screening_log``). Cooldowns are **not** parsed out of its prose: they
are derived from ``application_date`` by ``screening.cooldown``, and every
company named in that prose already has an application record.

Usage::

    python scripts/migrate_jobs_history.py --jobs /path/to/Jobs [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run as ``python scripts/migrate_jobs_history.py`` and Python puts scripts/ on
# the path rather than the repo root, so the application packages below would
# not resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import applications.store as app_store  # noqa: E402
from applications.model import flatten_notes  # noqa: E402
import screening.store as screening_store  # noqa: E402
from storage import data_dir  # noqa: E402

MANIFEST_NAME = "jobs_migration_manifest.json"

# Backups and the manifest go in a SUBDIRECTORY of the volume, never beside
# the stores. ``GET /api/download/{name}`` serves data_dir() by bare filename
# and rejects any name containing a separator, so a subdirectory is out of its
# reach -- and a backup is a complete copy of the application history,
# including the phone number and address in ``fields_submitted``.
MIGRATION_SUBDIR = "migration"

# Marks a screening row that exists only to carry a cooldown expiry forward.
COOLDOWN_CRITERION = "cooldown"

# Jobs record fields that map straight onto an editable Application field.
_DIRECT_FIELDS = {
    "company": "company",
    "role": "role",
    "url": "application_url",
    "ats": "ats",
    "applied_date": "application_date",
    "status": "status",
    "capture_method": "capture_method",
}


# --- reading the Jobs side -----------------------------------------------------

def load_records(jobs_dir: Path) -> list[dict]:
    """Every Jobs application record, oldest first, as raw dicts.

    Raises FileNotFoundError if the records directory is absent, because an
    empty import is far more likely to mean "wrong --jobs path" than "nothing
    to migrate", and silently importing zero records would look like success.
    """
    records_dir = jobs_dir / "applications" / "records"
    if not records_dir.is_dir():
        raise FileNotFoundError(f"no records directory at {records_dir}")
    records = []
    for path in sorted(records_dir.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def natural_key(company: str, role: str, date: str) -> tuple[str, str, str]:
    """The identity of an application for dedupe: company, role and date.

    Compared case- and whitespace-insensitively so a re-run matches rows it
    wrote itself even after an editor has touched them.
    """
    return (
        (company or "").strip().casefold(),
        (role or "").strip().casefold(),
        (date or "").strip(),
    )


def record_key(record: dict) -> tuple[str, str, str]:
    """The natural key of a Jobs record."""
    return natural_key(
        record.get("company", ""), record.get("role", ""), record.get("applied_date", "")
    )


# --- attachments ---------------------------------------------------------------

def _looks_like_path(value: str) -> bool:
    """Whether an attachment's ``path`` is a real filename and not prose.

    Two Jobs records (Sirius, Meridian) use the attachment slot to explain that
    the employer offered no upload field, putting a sentence where a path
    belongs. Copying those as filenames would fail noisily or, worse, create
    junk on the volume.
    """
    value = (value or "").strip()
    if not value or len(value) > 200 or " " in value:
        return False
    return Path(value).suffix.lower() in {".pdf", ".docx", ".html", ".md", ".txt"}


def copy_attachment(
    jobs_dir: Path, src_rel: str, app_id: str, slot: int, dry_run: bool
) -> str:
    """Copy one attachment onto the data volume; returns its volume filename.

    ``slot`` is the attachment's position on its record, so two attachments
    that share a basename cannot land on the same name and silently become one
    file. Returns "" when the source is missing, so a lost attachment downgrades
    that one row's evidence instead of aborting the whole migration.
    """
    src = jobs_dir / src_rel
    if not src.is_file():
        return ""
    dest_name = f"jobs_{app_id}_{slot}_{Path(src_rel).name}"
    if not dry_run:
        shutil.copy2(src, data_dir() / dest_name)
    return dest_name


def build_attachments(jobs_dir: Path, record: dict, app_id: str, dry_run: bool) -> list[dict]:
    """The attachment evidence for one record, with files copied to the volume.

    Entries whose ``path`` is prose rather than a filename are kept verbatim so
    the explanation ("no cover-letter upload field") is not silently lost.
    """
    out = []
    for slot, raw in enumerate(record.get("attachments") or []):
        path = raw.get("path", "")
        if not _looks_like_path(path):
            out.append({"kind": raw.get("kind", ""), "path": path})
            continue
        copied = copy_attachment(jobs_dir, path, app_id, slot, dry_run)
        out.append({"kind": raw.get("kind", ""), "path": copied or path})
    return out


# --- the screening log ---------------------------------------------------------

_SECTION_RE = re.compile(r"^# Screening record\s+[—-]\s*(\d{4}-\d{2}-\d{2})\s*$")

# The sentence that introduces the rejected-roles table. Across the six dated
# sections it appears as a "##" heading and as an ordinary paragraph, and with
# and without the word "today" -- so match the shape, not one exact wording.
_REJECTED_HEADING = re.compile(r"roles examined\b.*\brejected")


def _clean_cell(text: str) -> str:
    """Strip markdown emphasis and backticks from one table cell."""
    return re.sub(r"[*`]+", "", text).strip()


def _split_companies(cell: str) -> list[tuple[str, str]]:
    """Split a "Company — Role" table cell into (company, role) pairs.

    A cell naming several companies with no role ("Cyberdyne, Oceanic, ...")
    becomes one pair each; anything carrying a role stays whole, because
    splitting a role on its commas would invent companies that do not exist.
    """
    cell = _clean_cell(cell)
    if "—" in cell:
        company, _, role = cell.partition("—")
        return [(company.strip(), role.strip())]
    if "," in cell:
        return [(part.strip(), "") for part in cell.split(",") if part.strip()]
    return [(cell, "")]


def _is_separator(cells: list[str]) -> bool:
    """Whether a table row is the ``| --- | --- |`` rule under the header."""
    return all(set(cell) <= set("- :") for cell in cells)


def _starts_table(line: str) -> bool:
    """Whether this line introduces the rejected-roles table.

    Only the newest dated section writes it as a ``##`` heading; the five
    older ones write the same sentence as an ordinary paragraph, and the
    oldest drops the word "today". Matching the sentence's shape rather than
    the heading is what makes all six sections parse.
    """
    return bool(_REJECTED_HEADING.search(_clean_cell(line).lower()))


def _rejection_rows(lines: list[str]) -> list[list[str]]:
    """The data rows of every rejected-roles table in one dated section.

    The first pipe row of a table is its header and the second is the rule
    beneath it; both are skipped, because a header taken as data would import
    a screening record for a company literally called "Company / role".
    """
    rows: list[list[str]] = []
    armed = seen_header = False
    for line in lines:
        if _starts_table(line):
            armed, seen_header = True, False
        elif not armed:
            continue
        elif line.startswith("#"):
            armed = False
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not seen_header:
                seen_header = True
            elif not _is_separator(cells):
                rows.append(cells)
        elif seen_header and line.strip():
            armed = False
    return rows


# Phrases in the "failing criterion" cell that mean the target was NOT ruled
# out. Recording these as rejections would tell the agent a company is closed
# when the log says the opposite.
_DEFERRED_MARKERS = (
    "deferred",
    "not resolved",
    "carry to the next run",
    "cooldown",
    "no filter failed",
    "could not verify",
    "posting not live",
)


def _verdict_for(criterion: str) -> str:
    """Classify a table row as a rejection or a deferral.

    The table collects everything examined, not only what failed on merit: a
    row may record a cooldown, an unfinished check carried to the next run, a
    target abandoned mid-form, a posting that had already closed, or a site
    that could not be reached. None of those rule the company out, and filing
    them as rejections would tell the agent a door is shut that is not.
    """
    lowered = criterion.lower()
    if any(marker in lowered for marker in _DEFERRED_MARKERS):
        return "deferred"
    return "rejected"


def _sections(text: str) -> list[tuple[str, list[str]]]:
    """The log split into (date, lines) sections, one per dated screening run."""
    sections: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        match = _SECTION_RE.match(line)
        if match:
            sections.append((match.group(1), []))
        elif sections:
            sections[-1][1].append(line)
    return sections


_COOLDOWN_HEADING = re.compile(r"blocked by cooldown")
# "(to 2026-09-12" may be followed by an aside before the closing bracket, e.g.
# "(to 2026-09-13 — applied today; **new**)", so do not require the date to end
# the group.
_COOLDOWN_RE = re.compile(r"([^.()]+?)\s*\(to (\d{4}-\d{2}-\d{2})[^)]*\)")


def _cooldown_names(blob: str) -> list[str]:
    """The company names in one "A, B and C (to <date>)" clause."""
    cleaned = _clean_cell(blob).lstrip(".;:").strip()
    parts = re.split(r",|\band\b", cleaned)
    return [p.strip(" .") for p in parts if p.strip(" .")]


def parse_cooldowns(path: Path) -> dict[str, str]:
    """Company -> cooldown expiry date, read verbatim from the log's prose.

    The log is the only account of these dates. They are *not* recomputed from
    application dates: the log's own cooldown is about a month while the app's
    default is ninety days, so recomputing would silently replace what the user
    recorded with a different number.

    Only the newest still-live block is used -- later sections supersede
    earlier ones, and the newest section carries every live cooldown forward
    in full, so the first block encountered wins.
    """
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    seen: set[str] = set()
    for _date, lines in _sections(path.read_text(encoding="utf-8")):
        for name, expires in _cooldown_clauses(lines):
            if name.casefold() in seen:
                continue
            seen.add(name.casefold())
            out[name] = expires
    return out


def _cooldown_block(lines: list[str]) -> str:
    """The cooldown prose of one section, rejoined into a single string.

    The sentences wrap mid-clause, so a company and its expiry regularly sit on
    different lines. Reading line by line drops those pairs and splits company
    names in half, so the block is joined before anything is matched.
    """
    collected: list[str] = []
    armed = False
    for line in lines:
        cleaned = _clean_cell(line)
        if _COOLDOWN_HEADING.search(cleaned.lower()):
            armed = True
            collected.append(cleaned.split(":", 1)[-1])
            continue
        if not armed:
            continue
        if line.startswith("#") or _starts_table(line) or not line.strip():
            armed = False
            continue
        collected.append(cleaned)
    return " ".join(collected)


def _cooldown_clauses(lines: list[str]) -> list[tuple[str, str]]:
    """Every (company, expiry) pair in a section's cooldown prose."""
    pairs = []
    for blob, expires in _COOLDOWN_RE.findall(_cooldown_block(lines)):
        pairs.extend((name, expires) for name in _cooldown_names(blob))
    return pairs


def parse_screening_log(path: Path) -> list[dict]:
    """Rejected targets from the hand-written screening log, one row each.

    The log is prose, so this reads only the one machine-shaped part of it: the
    "roles examined today and rejected" table in each dated section. The full
    evidence cell is carried over verbatim into ``reason`` -- lossy structure,
    but no lost text. ``cooldown_expires`` is left empty on purpose: cooldowns
    derive from application dates, not from rejections.
    """
    if not path.is_file():
        return []
    out = []
    for date, lines in _sections(path.read_text(encoding="utf-8")):
        for cells in _rejection_rows(lines):
            if len(cells) < 3 or not _clean_cell(cells[0]):
                continue
            criterion = _clean_cell(cells[1])
            for company, role in _split_companies(cells[0]):
                out.append(
                    {
                        "company": company,
                        "role": role,
                        "screened_date": date,
                        "verdict": _verdict_for(criterion),
                        "failing_criterion": criterion,
                        "reason": _clean_cell(cells[2]),
                        "source": "imported",
                    }
                )
    return out


# --- safety --------------------------------------------------------------------

def migration_dir() -> Path:
    """The volume subdirectory holding backups and the manifest."""
    return data_dir() / MIGRATION_SUBDIR


def assert_readable(path: Path) -> None:
    """Refuse to continue if an existing store file does not parse.

    The stores fail safe to an empty list on malformed JSON, so writing after a
    failed read would replace real history with only what this run imported.
    A file holding anything but a JSON list is rejected for the same reason:
    ``load_all`` would yield nothing from it and the write would follow.
    """
    if not path.exists():
        return
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"refusing to migrate: {path} exists but does not parse ({exc})")
    if not isinstance(parsed, list):
        raise SystemExit(
            f"refusing to migrate: {path} holds {type(parsed).__name__}, not a list"
        )


def back_up(path: Path, stamp: str) -> Path | None:
    """Copy a store file into the migration subdirectory; None if absent.

    Fails loudly if a backup of that name already exists rather than
    overwriting one, so two runs in the same second cannot cost a backup.
    """
    if not path.exists():
        return None
    target_dir = migration_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    backup = target_dir / f"{path.stem}.{stamp}.bak{path.suffix}"
    if backup.exists():
        raise SystemExit(f"refusing to overwrite an existing backup: {backup}")
    shutil.copy2(path, backup)
    return backup


# --- importing -----------------------------------------------------------------

# Jobs record keys this importer knowingly does not carry onto an Application.
# ``application_id`` and ``schema_version`` describe the Jobs file itself, not
# the application, so they have no home in the ledger.
_KNOWN_KEYS = set(_DIRECT_FIELDS) | {
    "application_id",
    "schema_version",
    "notes",
    "gaps_disclosed",
    "fields_submitted",
    "confirmation",
    "screening",
    "attachments",
}


def unmapped_keys(record: dict) -> list[str]:
    """Keys on a Jobs record that this importer does not carry across.

    Reported rather than discarded silently: a key appearing here means the
    source schema has moved on and something is being dropped on the floor.
    """
    return sorted(set(record) - _KNOWN_KEYS)


def _editable_fields(record: dict) -> dict:
    """The Jobs record projected onto Application's editable fields."""
    fields = {dest: record.get(src, "") for src, dest in _DIRECT_FIELDS.items()}
    fields["submitted"] = record.get("status") == "confirmed"
    fields["submission_type"] = "Posting" if record.get("url") else "General"
    fields["method"] = record.get("ats", "")
    fields["gaps_disclosed"] = record.get("gaps_disclosed") or []
    fields["notes"] = flatten_notes(record.get("notes"))
    return fields


def import_record(jobs_dir: Path, record: dict, dry_run: bool) -> str:
    """Create one application from a Jobs record and attach its evidence.

    Returns the new application id ("" on a dry run, which creates nothing).
    """
    if dry_run:
        return ""
    app = app_store.create(_editable_fields(record))
    app_store.save_fields_submitted(app.id, record.get("fields_submitted") or [])
    app_store.save_confirmation(app.id, record.get("confirmation") or {})
    app_store.save_screening(app.id, record.get("screening") or {})
    app_store.save_attachments(
        app.id, build_attachments(jobs_dir, record, app.id, dry_run)
    )
    return app.id


def import_applications(jobs_dir: Path, records: list[dict], dry_run: bool) -> dict:
    """Import every record not already present; returns a report of the run."""
    existing = {natural_key(a.company, a.role, a.application_date) for a in app_store.load_all()}
    imported, skipped = [], []
    for record in records:
        if record_key(record) in existing:
            skipped.append(record.get("application_id", ""))
            continue
        app_id = import_record(jobs_dir, record, dry_run)
        existing.add(record_key(record))
        imported.append({"jobs_id": record.get("application_id", ""), "app_id": app_id})
    return {"imported": imported, "skipped": skipped}


def cooldown_rows(cooldowns: dict[str, str]) -> list[dict]:
    """One screening row per still-live cooldown, carrying its recorded expiry.

    These are not rejections: the company was never examined on merit. They
    exist so the expiry the user wrote down survives the Jobs repo, rather than
    being recomputed from a different rule.
    """
    return [
        {
            "company": company,
            "role": "",
            "screened_date": "",
            "verdict": "deferred",
            "failing_criterion": COOLDOWN_CRITERION,
            "reason": "Cooldown carried forward verbatim from SCREENING_LOG.md.",
            "cooldown_expires": expires,
            "source": "imported",
        }
        for company, expires in sorted(cooldowns.items())
    ]


def import_cooldowns(rows: list[dict], dry_run: bool) -> dict:
    """Import cooldown rows, keyed on company so a re-run adds nothing."""
    existing = {
        s.company.strip().casefold()
        for s in screening_store.load_all()
        if s.failing_criterion == COOLDOWN_CRITERION
    }
    imported, skipped = 0, 0
    for row in rows:
        key = row["company"].strip().casefold()
        if key in existing:
            skipped += 1
            continue
        if not dry_run:
            screening_store.create(row)
        existing.add(key)
        imported += 1
    return {"imported": imported, "skipped": skipped}


def import_screenings(rows: list[dict], dry_run: bool) -> dict:
    """Import screening rows that are not already on the volume."""
    existing = {
        natural_key(s.company, s.role, s.screened_date) for s in screening_store.load_all()
    }
    imported, skipped = 0, 0
    for row in rows:
        key = natural_key(row["company"], row["role"], row["screened_date"])
        if key in existing:
            skipped += 1
            continue
        if not dry_run:
            screening_store.create(row)
        existing.add(key)
        imported += 1
    return {"imported": imported, "skipped": skipped}


# --- entry point ---------------------------------------------------------------

def _write_manifest(report: dict, dry_run: bool) -> None:
    """Record what this run imported, so the migration can be audited later."""
    if dry_run:
        return
    migration_dir().mkdir(parents=True, exist_ok=True)
    path = migration_dir() / MANIFEST_NAME
    history = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(report)
    path.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")


def _unclassified(path: Path) -> list[str]:
    """Rejected-table rows too short to read, reported rather than dropped.

    A row that never becomes a screening record is a target the agent will not
    know was already ruled out, so it must surface in the run report instead of
    being skipped in silence.
    """
    if not path.is_file():
        return []
    out = []
    for date, lines in _sections(path.read_text(encoding="utf-8")):
        for cells in _rejection_rows(lines):
            if len(cells) < 3 or not _clean_cell(cells[0]):
                out.append(f"{date}: {' | '.join(cells)[:120]}")
    return out


def _prepare(dry_run: bool) -> list[str]:
    """Check both store files parse, then back them up. Returns backup names."""
    paths = [app_store.applications_path(), screening_store.screenings_path()]
    for path in paths:
        assert_readable(path)
    if dry_run:
        return []
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return [b.name for b in (back_up(p, stamp) for p in paths) if b]


def run(jobs_dir: Path, dry_run: bool) -> dict:
    """Migrate applications and screening history; returns the run report."""
    records = load_records(jobs_dir)
    backups = _prepare(dry_run)
    apps = import_applications(jobs_dir, records, dry_run)
    log_path = jobs_dir / "applications" / "SCREENING_LOG.md"
    screenings = import_screenings(parse_screening_log(log_path), dry_run)
    cooldowns = import_cooldowns(cooldown_rows(parse_cooldowns(log_path)), dry_run)
    report = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "source": str(jobs_dir),
        "dry_run": dry_run,
        "backups": backups,
        "records_found": len(records),
        "applications": apps,
        "screenings": screenings,
        "cooldowns": cooldowns,
        "unmapped_record_keys": {
            r.get("application_id", ""): unmapped_keys(r)
            for r in records
            if unmapped_keys(r)
        },
        "unclassified_log_rows": _unclassified(log_path),
    }
    _write_manifest(report, dry_run)
    return report


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the migration, and print the report as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--jobs", required=True, type=Path, help="path to the Jobs tree")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would change, write nothing"
    )
    args = parser.parse_args(argv)
    report = run(args.jobs, args.dry_run)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
