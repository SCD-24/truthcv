"""Operator-editable synonym map: equivalence groups of interchangeable forms.

An operator supplies data/vocabulary/synonyms.txt, one equivalence group per
line with forms separated by '='. Blank lines and lines starting with '#' are
skipped, and each form is stripped of surrounding whitespace. This lets the
pipeline treat, e.g., 'CI/CD' and 'Continuous Integration and Continuous
Delivery' as the same claim without any code change. A missing OR unreadable
file simply means no synonyms — callers degrade to exact matching rather than
failing a run.
"""

from __future__ import annotations

import logging

from truth.store import data_dir

# Per-data_dir cache of the parsed synonym groups; initialised lazily by
# synonym_groups() so import order never touches the filesystem. A test may
# reset it with `vocabulary.synonyms._synonyms_cache = None`.
_synonyms_cache: tuple[str, tuple[frozenset[str], ...]] | None = None


def _parse_line(line: str) -> frozenset[str] | None:
    """Parse one file line into a lowercased equivalence group.

    Args:
        line: A raw line from the synonyms file.

    Returns:
        A frozenset of the line's lowercased, stripped forms, or ``None`` when
        the line is blank, a comment, or holds only a single form (no group).
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None
    forms = {part.strip().lower() for part in stripped.split("=") if part.strip()}
    if len(forms) < 2:
        return None
    return frozenset(forms)


def _load_synonym_groups() -> tuple[frozenset[str], ...]:
    """Read and parse the operator synonyms file into equivalence groups.

    A missing file yields no groups with no warning; any other read error is
    logged and also yields no groups, so the pipeline never fails on it.

    Returns:
        One frozenset of lowercased forms per valid line-group.
    """
    path = data_dir() / "vocabulary" / "synonyms.txt"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except OSError as exc:
        logging.getLogger(__name__).warning(
            "Could not read %s (%s); using no synonyms", path, exc
        )
        return ()
    groups = [group for line in lines if (group := _parse_line(line)) is not None]
    return tuple(groups)


def synonym_groups() -> tuple[frozenset[str], ...]:
    """Return the operator-supplied equivalence groups, lowercased.

    Cached per data_dir so the file is read once per process.

    Returns:
        One frozenset of lowercased, interchangeable forms per group; an empty
        tuple when no synonyms file is present or readable.
    """
    global _synonyms_cache
    key = str(data_dir())
    if _synonyms_cache is None or _synonyms_cache[0] != key:
        _synonyms_cache = (key, _load_synonym_groups())
    return _synonyms_cache[1]


def equivalent_forms(term: str) -> frozenset[str]:
    """Return every other form equivalent to ``term`` across all groups.

    Args:
        term: The form to look up; matched case-insensitively.

    Returns:
        The union of all lowercased forms sharing a group with ``term`` (the
        term itself excluded), or an empty frozenset when it is in no group.
    """
    low = term.lower()
    others: set[str] = set()
    for group in synonym_groups():
        if low in group:
            others.update(group - {low})
    return frozenset(others)
