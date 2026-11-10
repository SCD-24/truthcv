"""Wire models for the truth document (the canonical CV source)."""

from __future__ import annotations

from pydantic import Field

from .common import _Camel


class BulletModel(_Camel):
    id: str
    value: str
    source: str = "uploaded-cv"


class ExperienceModel(_Camel):
    id: str
    role: str = ""
    company: str = ""
    start: str = ""
    end: str = ""
    source: str = "uploaded-cv"
    bullets: list[BulletModel] = Field(default_factory=list)


class EducationModel(_Camel):
    id: str
    degree: str = ""
    school: str = ""
    start: str = ""
    end: str = ""
    source: str = "uploaded-cv"


class SkillModel(_Camel):
    id: str
    value: str
    source: str = "uploaded-cv"


class HobbyModel(_Camel):
    id: str
    value: str
    source: str = "uploaded-cv"


class LinkModel(_Camel):
    label: str = ""
    url: str = ""


class ProfileModel(_Camel):
    """Personal header. Identity fields are guardrail-exempt; summary is a claim."""

    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[LinkModel] = Field(default_factory=list)
    summary: str = ""


class TruthDoc(_Camel):
    """The structured truth — GET /truth response and PUT /truth request body."""

    experiences: list[ExperienceModel] = Field(default_factory=list)
    education: list[EducationModel] = Field(default_factory=list)
    skills: list[SkillModel] = Field(default_factory=list)
    hobbies: list[HobbyModel] = Field(default_factory=list)
    profile: ProfileModel = Field(default_factory=ProfileModel)
