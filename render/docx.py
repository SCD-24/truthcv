"""HTML -> DOCX via pandoc (subprocess), written to the data volume."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from truth.store import data_dir

from .pdf import RenderUnavailable


def render_docx(html: str, filename: str = "cv.docx") -> Path:
    """Convert `html` to a DOCX file under DATA_DIR via pandoc; return its path."""
    if shutil.which("pandoc") is None:
        raise RenderUnavailable("pandoc is not installed in this environment.")

    out = data_dir() / filename
    src = data_dir() / "cv.render.html"
    src.write_text(html, encoding="utf-8")
    try:
        subprocess.run(
            ["pandoc", str(src), "-f", "html", "-o", str(out)],
            check=True,
            capture_output=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:  # noqa: PERF203
        raise RenderUnavailable(f"pandoc failed: {e.stderr.decode(errors='ignore')}") from e
    return out
