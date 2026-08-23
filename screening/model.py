"""Data shape for a job screening record.

A Screening records the outcome of evaluating one job posting against the
user's criteria: whether it was rejected, passed, or deferred, and — for a
rejection — which criterion it failed and why. ``cooldown_expires`` lets a
rejected posting be skipped on re-encounter until the cooldown lapses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

VERDICT_VALUES = ("rejected", "passed", "deferred")
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
    # Approval state. Deliberately absent from EDITABLE: that tuple is what
    # store.create()/update() copy from caller-supplied fields, and the agent's
    # record_screening(**fields) reaches create() directly. Listing these there
    # would let the agent approve its own applications. They are written only by
    # set_approval / record_apply_failure / mark_applied.
    approval: str = ""
    apply_attempts: int = 0
    apply_error: str = ""
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
