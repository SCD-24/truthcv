"""The screening workflows shared by the HTTP route and the MCP tool.

Only the parts that genuinely coincide are here. The two adapters keep their
own, deliberately different, contracts on top:

* **Duplicate handling.** `create_screening` returns ``(screening, created)``.
  The HTTP route raises a 409 carrying the existing screening's id when
  ``created`` is False; the MCP tool instead returns the existing record with
  ``created: false``. Both are correct for their caller and neither is
  "fixed" to match the other — see api/routes.py's create_screening
  docstring for why.
* **Validation and error tiers.** Each adapter validates its own inputs
  (the route via ``ScreeningCreate``'s pydantic validators, the tool via
  direct calls to ``screening.company``/``screening.model``/``screening.posting``)
  and raises in its own idiom (HTTPException vs ValueError/refusal dict).
  Only the terminal store call is shared.
"""

from __future__ import annotations

from dataclasses import dataclass

import screening.store as screening_store
from screening.store import Screening


def create_screening(fields: dict) -> tuple[Screening, bool]:
    """Create-or-get a screening from already-validated ``fields``.

    Returns ``(screening, created)`` — ``created`` is False when a screening
    for this posting already existed. What that means to the caller is the
    caller's decision (see the module docstring).
    """
    return screening_store.create_or_get(fields)


@dataclass
class ApplyClaimResult:
    """The outcome of claiming a screening for a manual/agent apply."""

    screening: Screening | None = None
    refused_screening: Screening | None = None
    reason: str = ""

    @property
    def refused(self) -> bool:
        return self.screening is None


def claim_screening_for_apply(screening_id: str) -> ApplyClaimResult:
    """Atomically retire ``screening_id`` so it can become an Application.

    Retire FIRST, atomically, and only the caller that wins the claim may go
    on to create the resulting Application row — two requests racing to
    create-then-retire would otherwise both succeed and leave two Application
    rows for the one screening.

    When the claim is refused, ``refused_screening`` is the current record
    (or None if it no longer exists at all) and ``reason`` is the same
    machine-readable refusal reason ``screening.store``'s private
    ``_apply_refusal`` derives — callers must not reach into that private
    function themselves; this is the one place that does.
    """
    screening = screening_store.claim_for_apply(screening_id)
    if screening is not None:
        return ApplyClaimResult(screening=screening)
    refused_screening = screening_store.get(screening_id)
    reason = (
        screening_store._apply_refusal(refused_screening)
        if refused_screening
        else "already_applied"
    )
    return ApplyClaimResult(refused_screening=refused_screening, reason=reason)
