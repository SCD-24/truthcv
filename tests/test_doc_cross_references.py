"""Cross-references between the live docs must resolve.

`agent/RUNBOOK.md` is read by the agent itself, so a pointer into it that names
the wrong rule sends the agent to the wrong rule. Two classes of rot are caught
here:

  - A numeric subsection pointer (`§5.5`). The RUNBOOK's sections are `## N.`
    headings whose bodies are ordered procedures; the items carry no anchors, so
    `§N.M` silently retargets the moment an item is inserted or removed.
  - A quoted section title that exists nowhere in the document it claims to cite.
    A stale number is at least a real place; an invented quotation never was one.
    `browser/README.md` shipped with one in e854501 and it went unnoticed.

The supported form is `§N "Exact Title"`, where the title appears verbatim as a
bolded item title or heading in the cited document. Quotes not attached to a `§`
are left alone — they are ordinarily literal values, not titles.

Citations are stripped from a document before it is searched, and the title must
land in a title rather than in running prose. Without both, a citation validates
against itself or against a sibling citation of the same rule, and renaming the
rule it points at leaves every pointer green.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# Current documentation. Dated design docs under docs/superpowers/ are records of
# what was decided at the time and are deliberately not held to today's wording,
# and .aether/.claude hold agent scratch state rather than docs.
LIVE_DOC_GLOBS = ("*.md", "agent/*.md", "browser/*.md", "docs/architecture/**/*.md",
                  "docs/conventions/**/*.md", "docs/domain/**/*.md")

# `§5 "Title"` and the possessive `§5's "Title"`.
CITATION = re.compile(r"§(\d+)(?:'s)?\s+\"([^\"]{4,160})\"")
NUMERIC_SUBSECTION = re.compile(r"§\d+\.\d+")
MD_PATH = re.compile(r"[\w./-]+\.md")
BOLD = re.compile(r"\*\*(.+?)\*\*")
# Anchored per line, against raw text: whitespace-collapsed text has no newlines
# for the heading body to stop at, so it would run on to the next '#' and swallow
# whole sections as "heading text", matching very nearly anything.
HEADING = re.compile(r"^#{1,6} +(.+)$", re.MULTILINE)


def _live_docs() -> list[Path]:
    found: set[Path] = set()
    for glob in LIVE_DOC_GLOBS:
        found.update(p for p in REPO.glob(glob) if p.is_file())
    return sorted(found)


def _flat(text: str) -> str:
    """Collapse whitespace so a hard-wrapped citation matches on one line."""
    return re.sub(r"\s+", " ", text)


def _resolve_target(flat: str, match_start: int, containing: Path) -> Path:
    """A citation naming a file cites that file; otherwise it cites its own."""
    preceding = flat[max(0, match_start - 200):match_start]
    for candidate in reversed(MD_PATH.findall(preceding)):
        path = REPO / candidate
        if path.is_file():
            return path
    return containing


def _titles_of(target: Path) -> str:
    """Bolded item titles and headings, with citations removed.

    Citations go first: a document that cites its own rule by title otherwise
    satisfies the check with the citation itself, so renaming the rule breaks
    nothing. Restricting to titles then keeps a phrase that merely occurs in
    running prose from standing in for the title it names.
    """
    raw = CITATION.sub(" ", target.read_text(encoding="utf-8"))
    # Bold from flattened text (a bolded title may be hard-wrapped across lines);
    # headings from raw text, so each stops at its own end of line.
    return " || ".join(BOLD.findall(_flat(raw)) + HEADING.findall(raw))


@pytest.mark.parametrize("doc", _live_docs(), ids=lambda p: str(p.relative_to(REPO)))
def test_no_numeric_subsection_references(doc: Path) -> None:
    """`§N.M` points at an unanchored list item and rots silently. Use a title."""
    stale = NUMERIC_SUBSECTION.findall(doc.read_text(encoding="utf-8"))
    assert not stale, (
        f"{doc.relative_to(REPO)} cites {sorted(set(stale))} by number. "
        'Cite the section and its verbatim title instead: §5 "Verify the '
        'submission actually landed".'
    )


@pytest.mark.parametrize("doc", _live_docs(), ids=lambda p: str(p.relative_to(REPO)))
def test_quoted_section_titles_exist(doc: Path) -> None:
    flat = _flat(doc.read_text(encoding="utf-8"))
    for match in CITATION.finditer(flat):
        section, title = match.group(1), match.group(2)
        target = _resolve_target(flat, match.start(), doc)
        assert title in _titles_of(target), (
            f"{doc.relative_to(REPO)} cites §{section} \"{title}\" but no bolded "
            f"item title or heading in {target.relative_to(REPO)} contains that "
            f"text."
        )


def test_the_check_covers_the_runbook_citations() -> None:
    """Guard the globs: a doc set that matched nothing would pass both tests."""
    runbook = _flat((REPO / "agent" / "RUNBOOK.md").read_text(encoding="utf-8"))
    assert CITATION.search(runbook), "RUNBOOK.md has no titled citations to check"
    assert (REPO / "browser" / "README.md") in _live_docs()
