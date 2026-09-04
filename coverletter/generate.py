"""Guardrail-truthful cover-letter generation.

The letter is produced as paragraphs of connective prose, each tagging the
factual claims it makes. Only those factual claims are validated by the guardrail
against the truth store; connective narrative is free. If any claim is
unverifiable the letter is blocked and nothing is returned as text.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from guardrail import BlockedClaim, Scope, validate
from providers.base import LLMProvider
from truth.answers import Answers
from truth.model import Truth
from storage import atomic_write_text, data_dir

import prompts


def _letter_draft_path() -> Path:
    """Where the last generated letter's paragraphs are cached.

    Persisting them lets an approve/decline round-trip re-validate the EXACT
    letter the user reviewed instead of a fresh LLM generation whose reworded
    claims would no longer match the ids the UI sent back.
    """
    return data_dir() / "cover_letter_draft.json"


def _posting_hash(posting: str | None) -> str | None:
    """Stable hash identifying which posting a cached draft belongs to."""
    if posting is None:
        return None
    return hashlib.sha256(posting.strip().encode("utf-8")).hexdigest()


def save_letter_draft(paragraphs: list[dict], posting: str | None = None) -> Path:
    """Cache the generated paragraphs so approvals can round-trip by claim id.

    The cache is bound to the posting it was generated for via a hash of the
    posting text, so a later ``load_letter_draft`` for a *different* posting
    never reuses a stale letter drafted for a job it no longer describes.
    """
    p = _letter_draft_path()
    envelope = {"postingHash": _posting_hash(posting), "paragraphs": paragraphs}
    atomic_write_text(p, json.dumps(envelope, indent=2))
    return p


def load_letter_draft(posting: str | None = None) -> list[dict] | None:
    """Reload the last generated letter's paragraphs for ``posting``.

    Returns None if no draft is cached, if the cached draft is the legacy
    bare-list format (stale, predates posting binding, forces regeneration),
    or if the cached draft's postingHash does not match ``posting`` (it was
    generated for a different job posting).
    """
    p = _letter_draft_path()
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return None
    if data.get("postingHash") != _posting_hash(posting):
        return None
    return data.get("paragraphs")

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "claims": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["text"],
            },
        }
    },
    "required": ["paragraphs"],
}


def _all_values(truth: Truth) -> list[str]:
    """Every factual value in the truth — the letter may reference any of them.

    Includes experiences, education, skills, and the profile header (name, email,
    phone, location, links, summary). A cover letter weaves the whole career, so
    validation is global here. Falsy values are dropped.
    """
    vals: list[str] = []
    for e in truth.experiences:
        vals += [e.role, e.company, e.start, e.end]
        vals += [b.value for b in e.bullets]
    for ed in truth.education:
        vals += [ed.degree, ed.school, ed.start, ed.end]
    vals += [s.value for s in truth.skills]
    # Profile header values
    profile = truth.profile
    vals += [profile.name, profile.email, profile.phone, profile.location, profile.summary]
    for link in profile.links:
        vals += [link.label, link.url]
    return [v for v in vals if v]


def _answer_values(answers: Answers | None) -> list[str]:
    """Every non-blank text field from the screening answers.

    Excludes canonical_cv_asset_id (an internal asset UUID, never a claim).
    Returns [] for None.
    """
    if not answers:
        return []
    # Every field except canonical_cv_asset_id
    fields = [
        answers.phone,
        answers.work_authorisation,
        answers.notice_period,
        answers.location_preference,
        answers.name,
        answers.email,
        answers.linkedin,
        answers.github,
        answers.website,
        answers.requires_sponsorship,
        answers.authorized_non_german_country,
        answers.languages,
        answers.highest_relevant_degree,
        answers.other_degree,
        answers.cs_degree,
        answers.gpa,
        answers.gender,
        answers.years_of_experience,
        answers.current_role,
        answers.how_did_you_hear,
    ]
    return [v for v in fields if v]


# Stable scope id for the letter's single validation scope. Callers derive a
# blocked-claim's id from (LETTER_SCOPE_ID, claim text), so this must not change
# without also updating the API's _claim_id round-trip.
LETTER_SCOPE_ID = "letter"


def build_letter(
    posting: str,
    tone: str,
    length: str,
    truth: Truth,
    provider: LLMProvider,
    approved_texts: set[str] | None = None,
    denied_texts: set[str] | None = None,
    paragraphs: list[dict] | None = None,
    answers: Answers | None = None,
    sign_off_name: str = "",
    preset_id: str | None = None,
) -> dict:
    """Generate a guardrailed cover letter.

    Returns {blocked, unverifiable, blocked_claims, text}; text is "" when
    blocked. ``approved_texts`` are claim strings the user has approved for THIS
    generation only — they are added to the guardrail's allowed set (never
    written to truth), mirroring the CV render approval flow. ``denied_texts``
    are dropped from the letter entirely so they can't ship: their paragraphs
    are excised BEFORE validation, so the guardrail only ever checks claims
    from paragraphs that will actually be emitted, and any resulting
    ``blocked_claims`` name only claims still present in the letter.

    ``paragraphs`` short-circuits the LLM: pass the cached paragraphs from a
    prior attempt (see load_letter_draft) so an approve/decline round-trip
    re-validates the SAME letter the user reviewed. When omitted, the letter is
    generated fresh and cached for the next round-trip.

    ``answers`` (optional screening answers) are passed to the guardrail as
    allowed claim sources for THIS generation only (never written to truth),
    along with profile-header values and approved_texts.

    ``sign_off_name`` appends a closing signature to the finished letter. It is
    added here, after validation, rather than asked of the model — which the
    style prompt explicitly forbids from writing the candidate's name — because
    a name the model types is a claim the guardrail must then check, and one it
    can get subtly wrong. Appended text is the operator's own stored name, so
    it asserts nothing new. A blank name appends nothing: a letter with no
    sign-off is correct, a letter signed "[Your Name]" is not.

    ``preset_id`` (optional) selects a writing style preset; when omitted,
    tone-based selection applies (backward compatible).
    """
    if paragraphs is None:
        paragraphs = _generate_paragraphs(
            posting, tone, length, truth, provider, answers, preset_id=preset_id
        )
        save_letter_draft(paragraphs, posting)

    shown = _excise_denied(paragraphs, denied_texts or set())
    scope = _letter_scope(shown, truth, approved_texts or set(), denied_texts or set(), answers)
    check = validate([scope])
    if not check.ok:
        return {
            "blocked": True,
            "unverifiable": check.unverifiable,
            "blocked_claims": check.blocked_claims,
            "text": "",
        }

    text = "\n\n".join(p["text"] for p in shown)
    leaked = _placeholders(text)
    if leaked:
        return {
            "blocked": True,
            "unverifiable": [],
            "blocked_claims": [
                BlockedClaim(scope_id=LETTER_SCOPE_ID, text=t, tokens=[t])
                for t in leaked
            ],
            "text": "",
        }
    return {
        "blocked": False,
        "unverifiable": [],
        "blocked_claims": [],
        "text": _with_sign_off(text, sign_off_name),
    }


# A signature is a name, not prose. The bound is deliberately generous — long
# double-barrelled names with post-nominals exist — while still refusing the
# sentence-length value that is the tell of a claim smuggled into the letter.
_MAX_SIGN_OFF_CHARS = 60


def _with_sign_off(text: str, name: str) -> str:
    """Append "Kind regards, / <name>" as the letter's closing paragraphs.

    Emitted as two blank-line-separated blocks because every consumer splits on
    the blank line: the HTML/DOCX renderers turn each into its own paragraph,
    and the agent pastes the raw text into an application form where a single
    newline would collapse.

    The name is appended after the guardrail has run, so it is checked here
    instead — against exactly what the guardrail would have caught:

    * ``_placeholders`` scans for a template slot ANYWHERE in the letter. An
      earlier version of this function guarded with ``fullmatch``, which is not
      the same test: "[Your Name] Smith" is not a whole-string placeholder, so
      it shipped a literal template slot to an employer.
    * A name long enough to be a sentence is refused. ``answers.name`` has no
      validator on the write path, and ``tools_letter`` deliberately does NOT
      pass the answers store to the guardrail as a claim source — so an
      unbounded value here would append an unvalidated factual claim
      ("ex-Google Staff Engineer with 15 years at NASA") to a guardrailed
      letter, after the only thing that checks claims has finished.

    Anything refused appends nothing: an unsigned letter is correct, a letter
    signed with a template slot or a resume line is not.
    """
    cleaned = " ".join(name.split()) if isinstance(name, str) else ""
    if not cleaned:
        return text
    if _placeholders(cleaned):
        return text
    if len(cleaned) > _MAX_SIGN_OFF_CHARS:
        return text
    return f"{text}\n\nKind regards,\n\n{cleaned}"


# A template slot the model failed to fill: "[Your Name]", "[Company]" — or
# the same slot written in any script, e.g. "[名前]" or "[Имя]". The character
# classes are Unicode-aware (\w with re.UNICODE) for exactly that reason; only
# digits are excluded from the first position so real bracketed prose like
# "[2024]" never trips it. The 0,38 length bound keeps genuine bracketed
# asides ("[sic]", short citations) out of the detector: a template slot holds
# a name/phrase, not a sentence.
_PLACEHOLDER = re.compile(r"\[[^\W\d][\w ./'-]{0,38}\]", re.UNICODE)


def _placeholders(text: str) -> list[str]:
    """Unfilled template placeholders in the finished letter.

    Nothing in this module emits a template — the letter is the model's own
    paragraphs joined — so a bracketed slot can only arrive if the model wrote
    one. Rare, but it ships straight to an employer when it happens, and no
    other check looks for it: the guardrail validates claims, and a placeholder
    asserts nothing to validate.
    """
    seen: list[str] = []
    for match in _PLACEHOLDER.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def _generate_paragraphs(
    posting: str,
    tone: str,
    length: str,
    truth: Truth,
    provider: LLMProvider,
    answers: Answers | None = None,
    preset_id: str | None = None,
) -> list[dict]:
    """Ask the provider for the letter's paragraphs + tagged factual claims.

    ``preset_id`` (optional) selects a writing style preset via the library;
    when omitted, tone-based selection applies.
    """
    user = f"POSTING:\n{posting}\n\nCANDIDATE FACTS:\n{prompts.cover_letter_facts_block(truth, answers)}"
    result = provider.extract_json(
        prompts.cover_letter_system_for_preset(preset_id, tone, length),
        [{"role": "user", "content": user}],
        _SCHEMA,
    )
    return result.get("paragraphs", []) if isinstance(result, dict) else []


def _excise_denied(paragraphs: list[dict], denied_texts: set[str]) -> list[dict]:
    """Drop any paragraph carrying a denied claim entirely, rather than trying
    to mutate its prose text. Matching denied claims against a paragraph's own
    `claims` list (not its free-form text) sidesteps casing/punctuation drift
    between the claim string and the prose, and dropping the whole paragraph
    avoids order-dependent overlapping-removal bugs. The originals (passed to
    save_letter_draft) are untouched so a later round-trip still sees them."""
    shown = []
    for p in paragraphs:
        claims = p.get("claims", [])
        if any(c in denied_texts for c in claims):
            continue
        shown.append(p)
    return shown


def _letter_scope(
    paragraphs: list[dict],
    truth: Truth,
    approved_texts: set[str],
    denied_texts: set[str],
    answers: Answers | None = None,
) -> Scope:
    """The single validation scope for the letter's factual claims.

    ``paragraphs`` is expected to already be the surviving set (post
    ``_excise_denied``), so validation only ever runs over — and any
    resulting ``blocked_claims`` only ever name — claims that will actually
    be emitted. Approved claim texts and answer values are appended to
    `allowed` (traceable for THIS generation only, no truth write); profile-
    header and screening-answer values are generation-scoped allowed sources
    never persisted to truth. The ``denied_texts`` filter here is a defensive
    no-op given already-excised input, kept in case this is ever called with
    un-excised paragraphs.
    """
    claims = [
        c
        for para in paragraphs
        for c in para.get("claims", [])
        if c and c not in denied_texts
    ]
    allowed = (
        _all_values(truth)
        + _answer_values(answers)
        + [t for t in approved_texts if t]
        + _facts_block_lines(truth, answers)
    )
    return Scope(id=LETTER_SCOPE_ID, texts=claims, allowed=allowed)


def _facts_block_lines(truth: Truth, answers: Answers | None) -> list[str]:
    """The facts block's own lines, as allowed claim sources.

    The block presents each fact labelled — ``Location: <city>`` — and the
    system prompt tells the model to list every fact it uses *verbatim* in its
    claims. A model that follows that instruction exactly emits the label too,
    and the label word ("location") appears in no truth value, so the guardrail
    flagged it and blocked the letter over a fact the operator really had.
    Whatever we present to the model as a fact has to be traceable when quoted
    back, so the block's lines are allowed sources alongside the raw values.
    """
    block = prompts.cover_letter_facts_block(truth, answers)
    return [line.strip() for line in block.splitlines() if line.strip()]
