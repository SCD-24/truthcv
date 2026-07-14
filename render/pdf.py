"""HTML -> PDF via WeasyPrint, written to the data volume."""

from __future__ import annotations

from pathlib import Path

from truth.store import data_dir


class RenderUnavailable(RuntimeError):
    """The rendering backend (WeasyPrint) is not installed in this environment."""


def render_pdf(html: str, filename: str = "cv.pdf") -> Path:
    """Render `html` to a PDF file under DATA_DIR and return its path."""
    try:
        from weasyprint import HTML  # imported lazily; heavy native deps
    except Exception as e:  # noqa: BLE001
        raise RenderUnavailable(f"WeasyPrint not available: {e}") from e

    out = data_dir() / filename
    HTML(string=html).write_pdf(str(out))
    return out
