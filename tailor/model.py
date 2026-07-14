"""Tailoring data structures — a structured, per-experience draft.

The draft mirrors the truth's shape: experiences (role/company/dates + rephrased
bullets), education, and skills. Header fields (role/company/dates, degree/school)
are copied verbatim from truth — only bullets are rephrased — and every block
carries the id of the truth object it came from, so the guardrail can validate
each block against its own experience.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DraftExperience:
    """One job in the tailored CV, traceable to a truth experience by id."""

    source_id: str
    role: str
    company: str
    dates: str
    bullets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "role": self.role,
            "company": self.company,
            "dates": self.dates,
            "bullets": list(self.bullets),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DraftExperience":
        return cls(
            source_id=str(d["sourceId"]),
            role=str(d.get("role", "")),
            company=str(d.get("company", "")),
            dates=str(d.get("dates", "")),
            bullets=[str(b) for b in d.get("bullets", []) or []],
        )


@dataclass
class DraftEducation:
    """One education entry in the tailored CV, traceable to truth by id."""

    source_id: str
    degree: str
    school: str
    dates: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "degree": self.degree,
            "school": self.school,
            "dates": self.dates,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DraftEducation":
        return cls(
            source_id=str(d["sourceId"]),
            degree=str(d.get("degree", "")),
            school=str(d.get("school", "")),
            dates=str(d.get("dates", "")),
        )


@dataclass
class Inference:
    """A claim the tailoring wants to add that is NOT yet in the truth store.

    Surfaced at the Confirm step; an approved one is written back as a
    user-confirmed bullet on `experience_id` before rendering.
    """

    id: str
    claim: str
    rationale: str
    experience_id: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "claim": self.claim,
            "rationale": self.rationale,
            "experienceId": self.experience_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Inference":
        return cls(
            id=str(d["id"]),
            claim=str(d["claim"]),
            rationale=str(d.get("rationale", "")),
            experience_id=str(d.get("experienceId", "")),
        )


@dataclass
class Draft:
    experiences: list[DraftExperience] = field(default_factory=list)
    education: list[DraftEducation] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    inferences: list[Inference] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiences": [e.to_dict() for e in self.experiences],
            "education": [e.to_dict() for e in self.education],
            "skills": list(self.skills),
            "keywords": list(self.keywords),
            "inferences": [i.to_dict() for i in self.inferences],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Draft":
        return cls(
            experiences=[DraftExperience.from_dict(x) for x in d.get("experiences", []) or []],
            education=[DraftEducation.from_dict(x) for x in d.get("education", []) or []],
            skills=[str(s) for s in d.get("skills", []) or []],
            keywords=list(d.get("keywords", [])),
            inferences=[Inference.from_dict(x) for x in d.get("inferences", []) or []],
        )
