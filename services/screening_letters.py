"""The operator's cover-letter workflow for one screening.

Behind ``POST`` and ``PUT /api/screenings/{id}/letter``. Generation goes
through ``services.letters.generate_cover_letter_for_operator`` — the same
guardrailed function the agent's own generation uses — and the draft is
persisted per screening in ``coverletter.store``. Both modules are looked up
at call time so tests can patch them. The provider comes from the caller as
``provider_factory``; this module never constructs one.
"""

from __future__ import annotations

import coverletter.store as letter_store
import screening.store as screening_store
import services.letters as _letters
import services.render_cv as _render_cv
from services.errors import Conflict, NotFound, Refused


def _screening_letter_approvals(
    approved_ids: set[str] | None,
    denied_ids: set[str] | None,
    paragraphs: list[dict] | None,
) -> tuple[set[str], set[str]]:
    """Resolve blocked-claim ids to claim texts against the paragraphs SUPPLIED
    IN THIS REQUEST, not the wizard's cached draft (_letter_approvals uses that
    one; it is wrong here — a screening's letter is per-screening, not global).
    Mirrors the wizard's id derivation exactly: LETTER_SCOPE_ID + _claim_id.

    ``approved_ids``/``denied_ids`` of None means the request carried no
    approvals at all.
    """
    if (approved_ids is None and denied_ids is None) or not paragraphs:
        return set(), set()

    from coverletter import LETTER_SCOPE_ID

    approved_ids = set(approved_ids or ())
    denied_ids = set(denied_ids or ())
    approved: set[str] = set()
    denied: set[str] = set()
    for para in paragraphs:
        for claim in para.get("claims", []):
            cid = _render_cv._claim_id(LETTER_SCOPE_ID, claim)
            if cid in approved_ids:
                approved.add(claim)
            if cid in denied_ids:
                denied.add(claim)
    return approved, denied


def _require_draftable(screening_id: str, force: bool):
    """The screening to draft for, or the 404/409 the route has always raised."""
    screening = screening_store.get(screening_id)
    if screening is None:
        raise NotFound("Screening not found.")
    if not screening.posting_text.strip():
        msg = "No posting text stored for this screening, so there is nothing to draft from."
        raise Conflict(msg, payload=msg)
    existing = letter_store.load(screening_id)
    if existing is not None and existing.source == "operator" and not force:
        msg = "This letter was edited by you. Redrafting would discard those edits."
        raise Conflict(msg, payload=msg)
    return screening


def _blocked_payload(result: dict) -> dict:
    """The structured 422 detail for a guardrail-blocked generation."""
    return {
        "message": "The letter was blocked by the truthfulness guardrail.",
        "blockedReason": result.get("blocked_reason", ""),
        "blockedClaims": [
            {
                "claimId": _render_cv._claim_id(c["scope_id"], c["text"]),
                "experienceId": c["scope_id"],
                "text": c["text"],
                "tokens": c["tokens"],
            }
            for c in result["blocked_claims"]
        ],
        "paragraphs": result["paragraphs"],
    }


def generate(
    screening_id: str,
    *,
    force: bool,
    approved_ids: set[str] | None,
    denied_ids: set[str] | None,
    paragraphs: list[dict] | None,
    preset_id: str | None,
    length: str,
    provider_factory,
) -> letter_store.CoverLetterDraft:
    """Draft the letter for one screening, on the operator's request.

    Guardrailed exactly as the agent's own generation is — this is the same
    function the agent calls. A blocked generation writes nothing and raises
    ``Refused`` carrying the claims that blocked it, so the operator can fix
    the truth document rather than discovering the block at approval time.

    A retry can carry approval ids and the blocked attempt's ``paragraphs`` to
    re-validate the SAME letter, mirroring `/api/cover-letter`.
    """
    screening = _require_draftable(screening_id, force)
    approved_texts, denied_texts = _screening_letter_approvals(
        approved_ids, denied_ids, paragraphs
    )
    result = _letters.generate_cover_letter_for_operator(
        posting=screening.posting_text,
        preset_id=preset_id,
        length=length,
        approved_texts=approved_texts,
        denied_texts=denied_texts,
        paragraphs=paragraphs,
        company=screening.company or None,
        provider_factory=provider_factory,
    )
    if result["blocked"]:
        raise Refused(
            "The letter was blocked by the truthfulness guardrail.",
            payload=_blocked_payload(result),
        )
    draft = letter_store.CoverLetterDraft(
        text=result["text"], paragraphs=result["paragraphs"], source="generated"
    )
    return letter_store.save(screening_id, draft)


def save_operator_text(screening_id: str, text: str) -> letter_store.CoverLetterDraft:
    """Save the operator's own text, verbatim and unvalidated.

    The one path in the system where text reaches an employer without passing
    guardrail/validate.py, and deliberately so: the guardrail exists to stop the
    AGENT asserting facts it cannot ground in the operator's truth document. The
    operator is the source of that document. `source` records that a human wrote
    this, and the agent applies with it unchanged.
    """
    if screening_store.get(screening_id) is None:
        raise NotFound("Screening not found.")
    if not text.strip():
        raise Refused(
            "An empty letter cannot be saved — blanking is not an edit; regenerate instead."
        )
    existing = letter_store.load(screening_id)
    draft = letter_store.CoverLetterDraft(
        text=text,
        paragraphs=existing.paragraphs if existing else [],
        source="operator",
    )
    return letter_store.save(screening_id, draft)
