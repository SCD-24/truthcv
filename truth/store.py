"""Persistence for truth.yaml against the ./data volume."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import yaml

from .model import SOURCE_VALUES, Truth


def data_dir() -> Path:
    """The mounted data volume (env DATA_DIR, default ./data)."""
    d = Path(os.environ.get("DATA_DIR", "./data"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def truth_path() -> Path:
    return data_dir() / "truth.yaml"


def _meta_path() -> Path:
    return data_dir() / "truth.meta.yaml"


def source_hash(text: str) -> str:
    """Stable fingerprint of profile source text, whitespace-normalized so
    trivial reflow doesn't look like a new profile."""
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def persist_source_hash(text: str) -> None:
    """Record which profile source produced the current truth.

    Why: lets extraction skip a fresh LLM pass (and its token cost) when the
    saved truth already came from this exact source text.
    """
    _meta_path().write_text(
        yaml.safe_dump({"source_hash": source_hash(text)}, sort_keys=False),
        encoding="utf-8",
    )


def loaded_source_hash() -> str | None:
    """The source hash tied to the persisted truth, or None if unknown."""
    p = _meta_path()
    if not p.exists():
        return None
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    value = raw.get("source_hash") if isinstance(raw, dict) else None
    return value or None


def validate(truth: Truth) -> None:
    """Enforce unique ids (across experiences, bullets, education, skills) and
    valid sources. Raises ValueError on violation."""
    seen: set[str] = set()

    def check_id(oid: str) -> None:
        if not oid:
            raise ValueError("Truth object has an empty id.")
        if oid in seen:
            raise ValueError(f"Duplicate truth id: {oid!r}")
        seen.add(oid)

    def check_source(src: str, oid: str) -> None:
        if src not in SOURCE_VALUES:
            raise ValueError(
                f"Invalid source {src!r} for {oid!r}; expected one of {SOURCE_VALUES}."
            )

    for exp in truth.experiences:
        check_id(exp.id)
        check_source(exp.source, exp.id)
        for b in exp.bullets:
            check_id(b.id)
            check_source(b.source, b.id)
    for edu in truth.education:
        check_id(edu.id)
        check_source(edu.source, edu.id)
    for sk in truth.skills:
        check_id(sk.id)
        check_source(sk.source, sk.id)


def load() -> Truth:
    """Load the structured truth from truth.yaml; empty if the file is missing.

    Fails safe on the pre-migration flat shape (`{entries: [...]}` or a bare
    list): returns an empty Truth so the user re-extracts into the new model
    rather than the app crashing on an incompatible file.
    """
    p = truth_path()
    if not p.exists():
        return Truth.empty()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict) or "entries" in raw:
        return Truth.empty()
    # experiences/education/skills are the content keys; "profile" is included so
    # a doc carrying only a profile header still round-trips instead of resetting.
    if not any(
        k in raw for k in ("experiences", "education", "skills", "profile")
    ):
        return Truth.empty()
    truth = Truth.from_dict(raw)
    validate(truth)
    return truth


def save(truth: Truth) -> Truth:
    """Validate then atomically write the truth to truth.yaml. Returns it."""
    validate(truth)
    p = truth_path()
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(truth.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp.replace(p)
    return truth
