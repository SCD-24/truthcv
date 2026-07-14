"""The structured truth model: experiences, education, and skills.

A fact is never standalone. A role, company, date range, and bullet all belong
to a specific *experience*, so a date can only ever be used with the job it came
from — the guardrail validates each fact in the context of its experience.
Education entries work the same way; skills are the one genuinely flat kind.

Provenance: header fields (role/company/dates, degree/school) inherit their
container's `source` — they are only ever extracted. Only bullets and skills
carry their own `source`, because a user-confirmed inference becomes a bullet.

Field names here are the keys the frontend client (web/src/api/types.ts) and the
persisted truth.yaml both use, so serialization is a straight dict of these.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

SOURCE_VALUES = ("linkedin-pdf", "user-confirmed")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")[:24] or "x"


def make_id(prefix: str, value: str, taken: set[str]) -> str:
    """Deterministic, collision-free id from a prefix + value.

    Same (prefix, value) always yields the same base id; on collision with a
    different value already taken, a numeric suffix is appended. `taken` is
    updated by the caller.
    """
    digest = hashlib.sha1(f"{prefix}:{value}".encode("utf-8")).hexdigest()[:6]
    base = f"{prefix}-{_slug(value)}-{digest}"
    if base not in taken:
        return base
    n = 2
    while f"{base}-{n}" in taken:
        n += 1
    return f"{base}-{n}"


@dataclass
class Bullet:
    """One achievement/responsibility line, owned by an experience."""

    id: str
    value: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "value": self.value, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Bullet":
        return cls(
            id=str(d["id"]),
            value=str(d["value"]),
            source=str(d.get("source", "linkedin-pdf")),
        )


@dataclass
class Experience:
    """One job: its role, company, date range, and bullets."""

    id: str
    role: str
    company: str
    start: str
    end: str
    source: str
    bullets: list[Bullet] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "company": self.company,
            "start": self.start,
            "end": self.end,
            "source": self.source,
            "bullets": [b.to_dict() for b in self.bullets],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Experience":
        return cls(
            id=str(d["id"]),
            role=str(d.get("role", "")),
            company=str(d.get("company", "")),
            start=str(d.get("start", "")),
            end=str(d.get("end", "")),
            source=str(d.get("source", "linkedin-pdf")),
            bullets=[Bullet.from_dict(b) for b in d.get("bullets", []) or []],
        )


@dataclass
class Education:
    """One qualification: degree, school, and date range."""

    id: str
    degree: str
    school: str
    start: str
    end: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "degree": self.degree,
            "school": self.school,
            "start": self.start,
            "end": self.end,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Education":
        return cls(
            id=str(d["id"]),
            degree=str(d.get("degree", "")),
            school=str(d.get("school", "")),
            start=str(d.get("start", "")),
            end=str(d.get("end", "")),
            source=str(d.get("source", "linkedin-pdf")),
        )


@dataclass
class Skill:
    """A standalone skill — the one flat kind."""

    id: str
    value: str
    source: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "value": self.value, "source": self.source}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Skill":
        return cls(
            id=str(d["id"]),
            value=str(d["value"]),
            source=str(d.get("source", "linkedin-pdf")),
        )


@dataclass
class Link:
    """A labelled profile link (e.g. LinkedIn, portfolio)."""

    label: str = ""
    url: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "url": self.url}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Link":
        return cls(label=str(d.get("label", "")), url=str(d.get("url", "")))


@dataclass
class Profile:
    """The single-user's personal header.

    Identity fields (name/contact/links) carry no provenance and are exempt from
    the guardrail; the free-text summary is a claim validated against the Truth
    File at render, so this stays a plain data holder with no id/source.
    """

    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "links": [link.to_dict() for link in self.links],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Profile":
        return cls(
            name=str(d.get("name", "")),
            email=str(d.get("email", "")),
            phone=str(d.get("phone", "")),
            location=str(d.get("location", "")),
            links=[Link.from_dict(link) for link in d.get("links", []) or []],
            summary=str(d.get("summary", "")),
        )


@dataclass
class Truth:
    """The whole record: grouped experiences and education, plus flat skills."""

    experiences: list[Experience] = field(default_factory=list)
    education: list[Education] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    profile: Profile = field(default_factory=Profile)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiences": [e.to_dict() for e in self.experiences],
            "education": [e.to_dict() for e in self.education],
            "skills": [s.to_dict() for s in self.skills],
            "profile": self.profile.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Truth":
        return cls(
            experiences=[Experience.from_dict(e) for e in d.get("experiences", []) or []],
            education=[Education.from_dict(e) for e in d.get("education", []) or []],
            skills=[Skill.from_dict(s) for s in d.get("skills", []) or []],
            profile=Profile.from_dict(d.get("profile") or {}),
        )

    @classmethod
    def empty(cls) -> "Truth":
        return cls([], [], [], Profile())

    def is_empty(self) -> bool:
        # Content-wise: a profile alone is still 'empty' (bootstrap unchanged).
        return not (self.experiences or self.education or self.skills)

    def all_ids(self) -> set[str]:
        ids: set[str] = set()
        for e in self.experiences:
            ids.add(e.id)
            ids.update(b.id for b in e.bullets)
        ids.update(e.id for e in self.education)
        ids.update(s.id for s in self.skills)
        return ids
