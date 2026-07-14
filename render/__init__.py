"""Renderer: assemble the approved CV into ATS-safe PDF and DOCX.

Rendering happens ONLY after the guardrail passes. The renderer builds from the
persisted draft and truth store; it adds no facts of its own.
"""

from .html import render_html
from .ats import lint
from .pdf import render_pdf
from .docx import render_docx

__all__ = ["render_html", "lint", "render_pdf", "render_docx"]
