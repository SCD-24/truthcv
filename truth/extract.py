"""Turn raw profile text into a structured, provenance-tagged Truth.

The provider only *proposes* structure — it groups the profile into experiences
(role/company/dates/bullets), education, and skills. Every fact is tagged
source='linkedin-pdf'; nothing is trusted until it flows back through the store
and, at render time, the guardrail (which now checks a fact against the specific
experience it belongs to).
"""

from __future__ import annotations

from typing import Any

from providers.base import LLMProvider

import prompts

from .model import Bullet, Education, Experience, Link, Profile, Skill, Truth, make_id
from . import store

_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "experiences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "company": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["role", "company", "start", "end", "bullets"],
            },
        },
        "education": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "degree": {"type": "string"},
                    "school": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                },
                "required": ["degree", "school", "start", "end"],
            },
        },
        "skills": {"type": "array", "items": {"type": "string"}},
        "profile": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "location": {"type": "string"},
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "url": {"type": "string"},
                        },
                    },
                },
                "summary": {"type": "string"},
            },
        },
    },
    "required": ["experiences", "education", "skills"],
}


def _build_profile(raw: Any) -> Profile:
    """Read the extracted profile header verbatim (identity carries no provenance)."""
    if not isinstance(raw, dict):
        return Profile()
    links: list[Link] = []
    for link in raw.get("links", []) or []:
        if not isinstance(link, dict):
            continue
        label = str(link.get("label", "")).strip()
        url = str(link.get("url", "")).strip()
        if label or url:
            links.append(Link(label=label, url=url))
    return Profile(
        name=str(raw.get("name", "")).strip(),
        email=str(raw.get("email", "")).strip(),
        phone=str(raw.get("phone", "")).strip(),
        location=str(raw.get("location", "")).strip(),
        links=links,
        summary=str(raw.get("summary", "")).strip(),
    )

def _cached_for(text: str) -> Truth | None:
    """Return the persisted truth if it was extracted from this exact source."""
    truth = store.load()
    if truth.is_empty():
        return None
    if store.loaded_source_hash() != store.source_hash(text):
        return None
    return truth


def build_truth_from_text(text: str, provider: LLMProvider) -> Truth:
    """Extract a structured Truth from `text`, tag source='linkedin-pdf', persist,
    and return it. Ids are stable and unique across the whole document.

    Reuses the already-persisted truth when it was produced from this exact source
    text (whitespace-normalized): a returning user re-visiting a saved profile
    skips the LLM pass entirely, so re-extraction costs no tokens. A different
    source (a new PDF) has a different hash and re-extracts as normal.
    """
    cached = _cached_for(text)
    if cached is not None:
        return cached
    result = provider.extract_json(
        prompts.extract_system(), [{"role": "user", "content": text}], _EXTRACTION_SCHEMA
    )
    if not isinstance(result, dict):
        result = {}
    taken: set[str] = set()

    experiences: list[Experience] = []
    for row in result.get("experiences", []) or []:
        role = str(row.get("role", "")).strip()
        company = str(row.get("company", "")).strip()
        if not role and not company:
            continue
        start = str(row.get("start", "")).strip()
        end = str(row.get("end", "")).strip()
        eid = make_id("exp", f"{role}|{company}|{start}", taken)
        taken.add(eid)
        bullets: list[Bullet] = []
        seen_b: set[str] = set()
        for bv in row.get("bullets", []) or []:
            value = str(bv).strip()
            if not value or value.lower() in seen_b:
                continue
            seen_b.add(value.lower())
            bid = make_id(f"{eid}-b", value, taken)
            taken.add(bid)
            bullets.append(Bullet(id=bid, value=value, source="linkedin-pdf"))
        experiences.append(
            Experience(
                id=eid, role=role, company=company, start=start, end=end,
                source="linkedin-pdf", bullets=bullets,
            )
        )

    education: list[Education] = []
    for row in result.get("education", []) or []:
        degree = str(row.get("degree", "")).strip()
        school = str(row.get("school", "")).strip()
        if not degree and not school:
            continue
        edid = make_id("edu", f"{degree}|{school}", taken)
        taken.add(edid)
        education.append(
            Education(
                id=edid, degree=degree, school=school,
                start=str(row.get("start", "")).strip(),
                end=str(row.get("end", "")).strip(),
                source="linkedin-pdf",
            )
        )

    skills: list[Skill] = []
    seen_s: set[str] = set()
    for sv in result.get("skills", []) or []:
        value = str(sv).strip()
        if not value or value.lower() in seen_s:
            continue
        seen_s.add(value.lower())
        sid = make_id("sk", value, taken)
        taken.add(sid)
        skills.append(Skill(id=sid, value=value, source="linkedin-pdf"))

    truth = Truth(
        experiences=experiences,
        education=education,
        skills=skills,
        profile=_build_profile(result.get("profile")),
    )
    store.save(truth)
    store.persist_source_hash(text)  # so a repeat of this source skips the LLM
    return truth


def write_confirmed(items: list[tuple[str, str]]) -> Truth:
    """Append user-confirmed inferences as bullets on their target experience.

    `items` is a list of (experience_id, claim). Each claim becomes a bullet with
    source='user-confirmed' on the named experience — or, if that id no longer
    exists, on the first experience (best effort). Duplicates and empties skip.
    """
    truth = store.load()
    taken = truth.all_ids()
    by_id = {e.id: e for e in truth.experiences}
    existing = {b.value.strip().lower() for e in truth.experiences for b in e.bullets}
    for exp_id, claim in items:
        value = str(claim).strip()
        if not value or value.lower() in existing:
            continue
        target = by_id.get(exp_id) or (truth.experiences[0] if truth.experiences else None)
        if target is None:
            continue  # no experience to attach to
        bid = make_id(f"{target.id}-b", value, taken)
        taken.add(bid)
        target.bullets.append(Bullet(id=bid, value=value, source="user-confirmed"))
        existing.add(value.lower())
    store.save(truth)
    return truth
