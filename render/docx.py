"""HTML -> DOCX via pandoc (subprocess), written to the data volume."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from storage import data_dir

from .pdf import RenderUnavailable


def render_docx(html: str, filename: str = "cv.docx") -> Path:
    """Convert `html` to a DOCX file under DATA_DIR via pandoc; return its path.

    The HTML is staged through a uniquely named temp file (rather than a
    shared fixed name) so concurrent conversions running in different threads
    never clobber each other's input; the temp file is removed afterwards
    regardless of outcome.
    """
    if shutil.which("pandoc") is None:
        raise RenderUnavailable("pandoc is not installed in this environment.")

    out = data_dir() / filename
    fd, src_name = tempfile.mkstemp(prefix="cv.render.", suffix=".html", dir=data_dir())
    src = Path(src_name)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(html)
        try:
            subprocess.run(
                ["pandoc", str(src), "-f", "html", "-o", str(out)],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except subprocess.CalledProcessError as e:  # noqa: PERF203
            raise RenderUnavailable(f"pandoc failed: {e.stderr.decode(errors='ignore')}") from e
    finally:
        src.unlink(missing_ok=True)
    return out
