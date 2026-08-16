"""Persistence for canonical ATS screening answers against the ./data volume.

Separate from truth.yaml: these are candidate-editable answers to recurring
application-screener questions (phone, work authorisation, salary band, ...)
rather than guardrail-validated CV facts, so they get their own file on the
same data volume and never touch the Truth Store's content or validation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from pathlib import Path

import yaml

from .store import data_dir


@dataclass
class Answers:
    """Canonical personal answers to common ATS screening questions.

    TruthCV ships with no identity: every field below starts blank (`""`)
    until seeded, so a fresh clone or a fresh data volume never carries
    anyone's personal data by default. `canonical_cv_asset_id` is the sole
    exception — it has no textual value to seed and instead defaults to
    None, since it is set by `register_canonical_cv`/`seed_canonical_cv`.
    """

    phone: str = ""
    work_authorisation: str = ""
    salary_expectation: str = ""
    notice_period: str = ""
    location_preference: str = ""
    canonical_cv_asset_id: str | None = None
    name: str = ""
    email: str = ""
    linkedin: str = ""
    github: str = ""
    website: str = ""
    requires_sponsorship: str = ""
    authorized_non_german_country: str = ""
    languages: str = ""
    highest_relevant_degree: str = ""
    other_degree: str = ""
    cs_degree: str = ""
    gpa: str = ""
    gender: str = ""
    years_of_experience: str = ""
    current_role: str = ""
    how_did_you_hear: str = ""

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "Answers":
        def text(key: str, default: str) -> str:
            value = d.get(key, default)
            return str(value) if value is not None else default

        asset_id = d.get("canonical_cv_asset_id")
        defaults = cls()
        return cls(
            phone=text("phone", defaults.phone),
            work_authorisation=text("work_authorisation", defaults.work_authorisation),
            salary_expectation=text("salary_expectation", defaults.salary_expectation),
            notice_period=text("notice_period", defaults.notice_period),
            location_preference=text("location_preference", defaults.location_preference),
            canonical_cv_asset_id=str(asset_id) if asset_id is not None else None,
            name=text("name", defaults.name),
            email=text("email", defaults.email),
            linkedin=text("linkedin", defaults.linkedin),
            github=text("github", defaults.github),
            website=text("website", defaults.website),
            requires_sponsorship=text("requires_sponsorship", defaults.requires_sponsorship),
            authorized_non_german_country=text(
                "authorized_non_german_country", defaults.authorized_non_german_country
            ),
            languages=text("languages", defaults.languages),
            highest_relevant_degree=text(
                "highest_relevant_degree", defaults.highest_relevant_degree
            ),
            other_degree=text("other_degree", defaults.other_degree),
            cs_degree=text("cs_degree", defaults.cs_degree),
            gpa=text("gpa", defaults.gpa),
            gender=text("gender", defaults.gender),
            years_of_experience=text("years_of_experience", defaults.years_of_experience),
            current_role=text("current_role", defaults.current_role),
            how_did_you_hear=text("how_did_you_hear", defaults.how_did_you_hear),
        )


def answers_path() -> Path:
    return data_dir() / "answers.yaml"


def load() -> Answers:
    """Load the canonical ATS answers; a blank default record if unset.

    Unlike truth.yaml, a missing file isn't a bootstrap-empty state waiting on
    extraction — it's just the starting answer set, so callers always get a
    fully populated Answers instance to read or edit rather than None.
    """
    p = answers_path()
    if not p.exists():
        return Answers()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return Answers()
    return Answers.from_dict(raw)


def save(answers: Answers) -> Answers:
    """Atomically write the canonical ATS answers to answers.yaml. Returns it."""
    p = answers_path()
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(
        yaml.safe_dump(answers.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    tmp.replace(p)
    return answers


@dataclass
class CanonicalCvAsset:
    """A registered canonical CV: its download id and where it lives on disk."""

    asset_id: str
    path: Path


def register_canonical_cv(source: str | Path) -> Answers:
    """Copy `source` onto the shared data volume and record it as canonical.

    The destination filename never depends on `source`'s own name — it is
    always `canonical_cv<source-suffix>` (e.g. `canonical_cv.pdf`), so it is
    safe by construction (no '/', '\\', or '..') and re-registering a fresh
    export keeps one stable asset id that can never collide with the
    wizard's scratch `cv.pdf`/`cv.docx` or an application's `cv_{id}.pdf`.
    It is immediately servable via the existing `GET /api/download/{name}`
    route, which resolves `name` straight to `data_dir() / name`. The copy
    itself is atomic — written to a temp file on the data volume first, then
    renamed into place — so a reader never observes a partially written
    asset. Persists and returns the updated Answers with
    canonical_cv_asset_id set to that filename.
    """
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Canonical CV source not found: {src}")
    name = f"canonical_cv{src.suffix}"
    dest = data_dir() / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.replace(dest)
    answers = load()
    answers.canonical_cv_asset_id = name
    return save(answers)


def canonical_cv() -> CanonicalCvAsset | None:
    """Look up the registered canonical CV, or None if none is registered.

    Returns the asset id (usable as-is with `GET /api/download/{name}`)
    alongside its resolved path on the shared data volume. Rejects a stored
    asset id that isn't a bare, safe name ('/', '\\', or '..' in it) rather
    than trusting it blindly, and only resolves to a regular file — a
    missing path, a directory, or anything else on disk at that name yields
    None rather than a dangling or unsafe reference.
    """
    asset_id = load().canonical_cv_asset_id
    if not asset_id or "/" in asset_id or "\\" in asset_id or ".." in asset_id:
        return None
    path = data_dir() / asset_id
    if not path.is_file():
        return None
    return CanonicalCvAsset(asset_id=asset_id, path=path)


# The canonical CV PDF is personal data, so it is NOT version-controlled:
# assets/ is gitignored and a fresh clone will not contain it. The durable
# copy is the registered asset on the shared data volume
# (data/canonical_cv.pdf), which is what every reader actually resolves via
# canonical_cv(); this path is only a convenience default for seeding from a
# working tree that happens to hold the export at assets/canonical_cv.pdf.
# When it is absent, register_canonical_cv raises FileNotFoundError naming
# the path it wanted — pass an explicit source instead. Registering is an
# explicit, one-time operation (seed_canonical_cv, below); importing this
# module must never touch the filesystem or the data volume.
_LOCAL_CANONICAL_CV = Path(__file__).resolve().parent.parent / "assets" / "canonical_cv.pdf"


def seed_canonical_cv(source: str | Path = _LOCAL_CANONICAL_CV) -> Answers:
    """Register a canonical CV PDF as the canonical asset.

    Only runs when explicitly invoked (a seed script, an admin action) — never
    at module import, and never implicitly from load()/save(). `source`
    defaults to an un-versioned local export under assets/, which is absent in
    a fresh clone; pass the path explicitly (`python -m truth.answers <path>`)
    when registering a CV, a newer export, or a test double. An already
    registered asset on the data volume needs no re-seeding.
    """
    return register_canonical_cv(source)


def _is_blank(value: object) -> bool:
    """True for a seed-file value that counts as "not supplied": None, or a
    string that is empty or only whitespace."""
    return value is None or (isinstance(value, str) and value.strip() == "")


def _applicable_fields(raw: dict[str, object]) -> dict[str, str]:
    """The keys of `raw` that seed_answers will actually apply.

    Excludes keys not on `Answers`, `canonical_cv_asset_id` (registered
    separately, never seeded from the file), and any key whose value is
    blank per `_is_blank` (treated as "not supplied").
    """
    field_names = {f.name for f in fields(Answers)} - {"canonical_cv_asset_id"}
    return {
        key: str(raw[key]) for key in field_names & raw.keys() if not _is_blank(raw[key])
    }


def seed_answers(source: str | Path) -> Answers:
    """Merge text answers from a YAML file into the stored answers.

    `source` must be a mapping of `Answers` field names to values; unknown
    keys are ignored silently, and `canonical_cv_asset_id` in the file is
    never applied — that field is registered separately, by
    `register_canonical_cv`/`seed_canonical_cv`, and must survive seeding
    untouched. This merges rather than replaces: starting from the currently
    stored answers (`load()`), only the keys present in the file are
    overwritten, so any key absent from the file keeps its stored value.

    A key with no value (`gpa:` with nothing after it, which YAML parses as
    None) or a value that is empty or only whitespace is treated as "not
    supplied" and skipped, leaving the stored value alone — this is not a way
    to clear a field. To actually clear a field, use the Settings UI, which
    writes through `PUT /api/profile/answers`.
    """
    src = Path(source)
    if not src.is_file():
        raise FileNotFoundError(f"Answers seed file not found: {src}")
    raw = yaml.safe_load(src.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Answers seed file must contain a mapping: {src}")
    answers = load()
    for key, value in _applicable_fields(raw).items():
        setattr(answers, key, value)
    return save(answers)


if __name__ == "__main__":  # pragma: no cover
    # Explicit, one-time initialization, matching the `python -m api.genkey`
    # convention: `python -m truth.answers [source]` registers a canonical CV;
    # `python -m truth.answers --answers <path>` seeds text answers from a
    # YAML file instead. Never runs on import.
    import sys

    argv = sys.argv[1:]
    if argv and argv[0] == "--answers":
        seed_path = Path(argv[1])
        seed_answers(seed_path)
        raw = yaml.safe_load(seed_path.read_text(encoding="utf-8")) or {}
        applied = len(_applicable_fields(raw))
        if applied == 0:
            print(
                f"Seeded 0 answer field(s) from {seed_path}: nothing applied — "
                "every recognised key was blank, or no keys matched a known field"
            )
        else:
            print(f"Seeded {applied} answer field(s) from {seed_path}")
    else:
        source = argv[0] if argv else _LOCAL_CANONICAL_CV
        result = seed_canonical_cv(source)
        print(f"Registered canonical CV: {result.canonical_cv_asset_id}")
