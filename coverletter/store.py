"""Per-screening cover letter drafts on the data volume.

One JSON file per screening under data/letters/, plus — once something has
rendered it — a PDF of that text flat in data/ (see `pdf_filename`), which is
the file the unattended agent uploads to an employer. Kept out of screenings.json
because the letter is rewritten repeatedly and dwarfs the record it belongs to,
and that file is loaded in full on every screening read.

`source` is the audit trail: "generated" means the text is exactly what
generate_cover_letter produced and the guardrail validated, "operator" means a
human rewrote it and the guardrail no longer vouches for it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from storage import data_dir

SOURCES = ("generated", "operator")


@dataclass
class CoverLetterDraft:
    """One screening's current letter."""

    text: str = ""
    paragraphs: list[dict] = field(default_factory=list)
    source: str = "generated"
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "CoverLetterDraft":
        kwargs = {}
        if "text" in raw and isinstance(raw["text"], str):
            kwargs["text"] = raw["text"]
        if "paragraphs" in raw and isinstance(raw["paragraphs"], list):
            kwargs["paragraphs"] = [p for p in raw["paragraphs"] if isinstance(p, dict)]
        # A wrong-typed source must not read as operator-authored: that would
        # claim a human vouched for text the guardrail wrote.
        if "source" in raw and raw["source"] in SOURCES:
            kwargs["source"] = raw["source"]
        if "updated_at" in raw and isinstance(raw["updated_at"], str):
            kwargs["updated_at"] = raw["updated_at"]
        return cls(**kwargs)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "paragraphs": self.paragraphs,
            "source": self.source,
            "updated_at": self.updated_at,
        }


def letters_dir() -> Path:
    """The directory holding one draft per screening."""
    return data_dir() / "letters"


def draft_path(screening_id: str) -> Path:
    """Path to one screening's draft.

    The id reaches this function from a URL path segment, so it is validated
    rather than trusted: anything with a separator or a parent reference could
    otherwise read or write outside the volume.
    """
    if not screening_id or "/" in screening_id or "\\" in screening_id or screening_id.startswith("."):
        raise ValueError(f"Unsafe screening id '{screening_id}'.")
    return letters_dir() / f"{screening_id}.json"


def pdf_filename(screening_id: str, text: str, header: str = "") -> str:
    """The rendered-letter filename for one screening's current letter.

    Flat in data_dir() rather than under letters/ because /api/download/{name}
    rejects any name with a separator, and this file is both what the agent
    uploads to an employer and what the operator downloads to see what went.

    The name carries a digest of everything that ends up in the document — the
    letter text AND the header the renderer draws from the operator's profile,
    since a PDF whose contact line is stale is as wrong as one whose prose is.
    So a file that exists is a file whose contents are known: an edit renders
    to a new name
    instead of overwriting the old one, and no reader needs to compare
    timestamps to decide whether a render is current. Superseded renders are
    swept by `prune_pdfs`, so one screening keeps one file. The `screening`
    segment namespaces these against the wizard's per-application
    `cover_letter_{app_id}.pdf`, drawn from the same 12-hex id space.
    """
    if not screening_id or "/" in screening_id or "\\" in screening_id or screening_id.startswith("."):
        raise ValueError(f"Unsafe screening id '{screening_id}'.")
    digest = hashlib.sha256(f"{header}\x00{text}".encode("utf-8")).hexdigest()[:16]
    return f"cover_letter_screening_{screening_id}_{digest}.pdf"


def pdf_path(screening_id: str, text: str, header: str = "") -> Path:
    """Filesystem path of the rendered letter for one screening's letter."""
    return data_dir() / pdf_filename(screening_id, text, header)


def pdf_glob(screening_id: str, include_staging: bool = False) -> str:
    """Every rendered letter belonging to one screening, current or superseded.

    ``include_staging`` widens the match to the ``.part`` files a render stages
    under. Only safe where nothing can be rendering this screening — deleting
    its draft — because a stage belonging to a render still in flight would
    otherwise be swept out from under it.
    """
    if not screening_id or "/" in screening_id or "\\" in screening_id or screening_id.startswith("."):
        raise ValueError(f"Unsafe screening id '{screening_id}'.")
    return f"cover_letter_screening_{screening_id}_*" if include_staging else f"cover_letter_screening_{screening_id}_*.pdf"


def prune_pdfs(screening_id: str, keep: str = "", include_staging: bool = False) -> int:
    """Delete this screening's rendered letters, except ``keep``. Returns the count.

    Renders are content-addressed, so an edited letter leaves its predecessor
    behind under the old digest. Nothing dereferences those: an application
    records the filenames it read off the employer's form, not a path on this
    volume. Left alone they would accumulate one private cover letter per edit,
    forever, with no route by which the operator could see or remove them.
    """
    try:
        pattern = pdf_glob(screening_id, include_staging)
    except ValueError:
        return 0
    removed = 0
    for stale in data_dir().glob(pattern):
        if stale.name == keep:
            continue
        try:
            stale.unlink()
        except OSError:  # a concurrent sweep got there first; nothing to repair
            continue
        removed += 1
    return removed


def load(screening_id: str) -> CoverLetterDraft | None:
    """The stored draft, or None when there is none or the file is unreadable."""
    try:
        p = draft_path(screening_id)
    except ValueError:
        return None
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return CoverLetterDraft.from_dict(raw)


def save(screening_id: str, draft: CoverLetterDraft) -> CoverLetterDraft:
    """Persist a draft atomically, stamping updated_at."""
    p = draft_path(screening_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    draft.updated_at = datetime.now(timezone.utc).isoformat()
    tmp = p.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(draft.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        tmp.replace(p)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    return draft


def delete(screening_id: str) -> bool:
    """Remove a draft. True if it existed."""
    try:
        p = draft_path(screening_id)
    except ValueError:
        return False
    if not p.exists():
        # The draft may already be gone while its renders are not — sweep them
        # anyway, so a lost JSON file cannot strand a letter on the volume.
        prune_pdfs(screening_id, include_staging=True)
        return False
    p.unlink()
    prune_pdfs(screening_id, include_staging=True)
    return True
