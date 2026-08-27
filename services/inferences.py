"""The confirm-inferences workflow: resolve approved claims and persist them."""

from __future__ import annotations

from typing import Iterable

import tailor as tailor_engine
from truth.extract import write_confirmed


def confirm_inferences(approved: Iterable | None, approved_ids: Iterable[str]) -> None:
    """Resolve the approved claims and write them as confirmed truth.

    Prefer the user-edited claims: the Confirm step lets the user reword an
    inferred claim (and re-target its experience) before it becomes a fact, so
    what they typed is what we persist. Fall back to the deprecated
    approved_ids path, which writes each id's original draft claim.

    ``approved``, if given, is an iterable of objects each carrying
    ``experience_id`` and ``claim`` attributes (e.g. the request's
    ``ConfirmedClaimModel`` entries) — duck-typed so this stays free of any
    schema import.
    """
    approved = list(approved) if approved else []
    if approved:
        # A re-targeted experienceId the client made up (not in the draft) is
        # dropped to "" so write_confirmed attaches it to a safe default rather
        # than trusting an id that points nowhere.
        known = tailor_engine.valid_experience_ids()
        claims = [
            (a.experience_id if a.experience_id in known else "", a.claim)
            for a in approved
        ]
    else:
        claims = tailor_engine.claims_for_ids(list(approved_ids))
    write_confirmed(claims)
