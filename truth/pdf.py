"""PDF text extraction for the uploaded CV export."""

from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .store import data_dir


class DocumentExtractError(ValueError):
    """The uploaded PDF is unreadable, encrypted, or empty."""


PdfExtractError = DocumentExtractError


def extract_text(file_bytes: bytes) -> str:
    """Return the concatenated text of every page of the PDF.

    Raises PdfExtractError on encrypted, corrupt, or text-empty PDFs.
    """
    if not file_bytes:
        raise PdfExtractError("Uploaded file is empty.")
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except PdfReadError as e:
        raise PdfExtractError(f"Could not read PDF: {e}") from e
    except Exception as e:  # noqa: BLE001 — pypdf raises varied types on odd PDFs
        raise PdfExtractError(
            "This PDF could not be parsed. Re-export your CV as a PDF and try again."
        ) from e

    if reader.is_encrypted:
        # Try empty password; LinkedIn exports are not encrypted.
        try:
            if reader.decrypt("") == 0:
                raise PdfExtractError("PDF is password-protected; remove the password and retry.")
        except Exception as e:  # noqa: BLE001
            raise PdfExtractError("PDF is password-protected; remove the password and retry.") from e

    parts: list[str] = []
    try:
        pages = list(reader.pages)
    except Exception as e:  # noqa: BLE001
        raise PdfExtractError(
            "This PDF's page structure could not be read. Re-export it and retry."
        ) from e
    for page in pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001
            parts.append("")
    text = "\n".join(p.strip() for p in parts if p.strip())
    if not text.strip():
        raise PdfExtractError(
            "No selectable text found in the PDF. Export your CV as a text PDF, "
            "not a scanned image."
        )
    return text


def persist_source_text(text: str) -> Path:
    """Store the raw extracted text so the extract step can consume it."""
    p = data_dir() / "source.txt"
    p.write_text(text, encoding="utf-8")
    return p


def load_source_text() -> str:
    p = data_dir() / "source.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def persist_profile(file_bytes: bytes, ext: str = ".pdf") -> Path:
    """Store the raw uploaded CV so the user need not re-upload each session.

    Only one stored profile file is kept: any other `profile.*` file already
    present in the data dir is removed before writing the new one.
    """
    d = data_dir()
    for existing in d.glob("profile.*"):
        existing.unlink()
    p = d / f"profile{ext}"
    p.write_bytes(file_bytes)
    return p


def has_profile() -> bool:
    """True if a stored profile file (any supported extension) exists."""
    return any(data_dir().glob("profile.*"))


def profile_path() -> Path | None:
    """The stored profile file, if one exists."""
    matches = list(data_dir().glob("profile.*"))
    return matches[0] if matches else None
