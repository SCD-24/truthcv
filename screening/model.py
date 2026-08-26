"""Data shape for a job screening record.

A Screening records the outcome of evaluating one job posting against the
user's criteria: whether it was rejected, passed, or deferred, and — for a
rejection — which criterion it failed and why. ``cooldown_expires`` lets a
rejected posting be skipped on re-encounter until the cooldown lapses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

VERDICT_VALUES = ("rejected", "passed", "deferred")

# A posting the agent could not read at all — 403, login wall, dead link,
# expired listing — is not a verdict on its merits. ``""`` means "no blocker".
BLOCKER_VALUES = ("", "login_required", "unreadable", "not_found", "expired")


def validate_verdict(verdict: str, blocker: str = "") -> str:
    """Return the verdict lowercased, or raise ``ValueError`` if not a known one.

    ``store.create`` routes a record into the operator's approval queue by
    comparing this value against ``"deferred"``/``"passed"``, so an unrecognised
    or empty verdict does not fail loudly — it silently produces a record the
    operator never sees. Checked at the agent's boundary rather than in the
    store, which stays lenient for the legacy importer.

    A verdict is normally required, but a posting the agent could not read has
    no merits to judge — passing a non-empty ``blocker`` allows an empty
    verdict in that one case. It is a ValueError for both to be empty, and an
    unrecognised non-empty verdict is always rejected regardless of blocker.
    """
    cleaned = verdict.strip().casefold() if isinstance(verdict, str) else ""
    has_blocker = bool(blocker.strip()) if isinstance(blocker, str) else False
    if not cleaned:
        if has_blocker:
            return ""
        raise ValueError(
            "A verdict is required — without one the screening never reaches "
            f"the operator's approval queue. Use one of: {', '.join(VERDICT_VALUES)}, "
            "or supply a screening_blocker if the posting could not be read."
        )
    if cleaned not in VERDICT_VALUES:
        raise ValueError(
            f"Unknown verdict {verdict!r}. Use one of: {', '.join(VERDICT_VALUES)}."
        )
    return cleaned


def validate_blocker(value: str) -> str:
    """Return the blocker lowercased, or raise ``ValueError`` if not a known one.

    Mirrors ``validate_verdict``'s normalisation. An empty string is a valid
    value meaning "no blocker".
    """
    cleaned = value.strip().casefold() if isinstance(value, str) else ""
    if cleaned not in BLOCKER_VALUES:
        raise ValueError(
            f"Unknown blocker {value!r}. Use one of: {', '.join(BLOCKER_VALUES)}."
        )
    return cleaned


APPROVAL_VALUES = ("", "pending", "approved", "rejected", "applied")
SOURCE_VALUES = ("agent", "imported", "manual")


@dataclass
class Screening:
    """One screening decision for a job posting."""

    id: str = ""
    company: str = ""
    role: str = ""
    url: str = ""
    screened_date: str = ""
    verdict: str = ""
    failing_criterion: str = ""
    reason: str = ""
    cooldown_expires: str = ""
    source: str = ""
    # The posting as the agent read it. Stored because the operator drafts the
    # letter from it later, in the app, long after the run that found it — and
    # several of these boards cannot be re-fetched at all.
    posting_text: str = ""
    # The employer's publication date, best-effort: many boards publish none.
    # Empty means unknown and is never inferred. `screened_date` is the date
    # this posting was found, which is a different thing.
    posted_date: str = ""
    # Approval state. Deliberately absent from EDITABLE: that tuple is what
    # store.create()/update() copy from caller-supplied fields, and the agent's
    # record_screening(**fields) reaches create() directly. Listing these there
    # would let the agent approve its own applications. They are written only by
    # set_approval / record_apply_failure / mark_applied.
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
    # Why the application could not be completed, when the reason is one the
    # app can act on rather than only display. Empty, or "login_required" when
    # the form sat behind a sign-in or registration wall. `apply_error` stays
    # the human-readable detail; this is what the sign-in queue filters on.
    apply_blocker: str = ""
    # The page the operator should sign in at, recorded alongside the blocker.
    signin_url: str = ""
    # Why the agent could not read the posting at all (see BLOCKER_VALUES),
    # distinct from apply_blocker above: apply_blocker describes a failure to
    # *submit* an application the agent did read and screen; screening_blocker
    # describes a posting the agent never got to evaluate in the first place.
    # Unlike apply_blocker/signin_url, this one IS in EDITABLE below — it is
    # the agent's own honest report of "I could not read this", made at
    # record_screening time, not a grant of approval or a routing decision.
    screening_blocker: str = ""
    # Lease state: which run currently holds this item and until when. Set
    # only by get_approved_applications' hand-out (screening.store.claim_for_run)
    # and cleared on release/retire — like approval, this is NOT in EDITABLE,
    # because a claim is granted by the hand-out call, not something the agent
    # is entitled to patch onto its own record. An expired claim_expires_at
    # means the item is unclaimed and reclaimable by another run.
    claimed_by_run: str = ""
    claim_expires_at: str = ""
    # The run that PRODUCED this screening — the opposite of claimed_by_run
    # above in lifetime. claimed_by_run is an ephemeral lease, cleared on
    # release and by store._retire; run_id is written once at record time and
    # must never be cleared, because it is the evidence the run record's
    # coverage counters are derived from (runs/derive.py). Empty means the
    # record belongs to no run (manual entry, or the historical import).
    run_id: str = ""
    created_at: str = ""
    updated_at: str = ""

    # Fields a client may set directly on create/update.
    EDITABLE = (
        "company",
        "role",
        "url",
        "screened_date",
        "verdict",
        "failing_criterion",
        "reason",
        "cooldown_expires",
        "source",
        "posting_text",
        "posted_date",
        "screening_blocker",
        # Which run produced this record. Editable so record_screening's
        # create() call can persist it; only ever set, never cleared.
        "run_id",
    )

    @classmethod
    def from_dict(cls, raw: dict) -> "Screening":
        known = {f for f in cls.__dataclass_fields__}
        values = {k: raw[k] for k in known if k in raw}
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


def new_id() -> str:
    """Short, filename-safe screening id."""
    import uuid

    return uuid.uuid4().hex[:12]
