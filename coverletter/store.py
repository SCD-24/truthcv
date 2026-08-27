"""Per-screening cover letter drafts on the data volume.

One JSON file per screening under data/letters/. Kept out of screenings.json
because the letter is rewritten repeatedly and dwarfs the record it belongs to,
and that file is loaded in full on every screening read.

`source` is the audit trail: "generated" means the text is exactly what
generate_cover_letter produced and the guardrail validated, "operator" means a
human rewrote it and the guardrail no longer vouches for it.
"""

from __future__ import annotations

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
        return False
    p.unlink()
    return True
