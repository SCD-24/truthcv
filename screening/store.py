"""Persistence for job screening records against the ./data volume.

Mirrors applications/store.py and truth/store.py: one JSON file on the shared
data volume.

Every function that mutates the list runs its whole load-modify-write inside
``datafile.locked``. The agent writes screenings over MCP into the same `app`
process the operator's browser talks to, so two writers racing here is routine
rather than exotic, and without the lock one of the two records is silently
dropped. See ``datafile`` for what each half of that guarantee buys.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentconfig.store import load as _agent_config_load
from companyresearch.store import open_contradictions as _open_contradictions
from datafile import atomic_write_text, locked
from truth.store import data_dir

from .model import APPROVAL_VALUES, Screening, new_id, validate_blocker


def screenings_path() -> Path:
    return data_dir() / "screenings.json"


def _now() -> str:
    """UTC ISO-8601 timestamp; single source so created/updated stay consistent."""
    return datetime.now(timezone.utc).isoformat()


def load_all() -> list[Screening]:
    """Every screening record; empty list if the file is missing or invalid.

    Fails safe on a malformed file (returns []) so a hand-edited or partially
    written JSON never crashes the app on startup.
    """
    p = screenings_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    return [Screening.from_dict(item) for item in raw if isinstance(item, dict)]


def _write_all(screenings: list[Screening]) -> None:
    """Persist the full list to screenings.json.

    Callers must already hold ``locked(screenings_path())`` — this writes the
    list it is given and does no reconciliation, so an unguarded caller
    overwrites whatever another writer stored since it loaded.
    """
    atomic_write_text(
        screenings_path(),
        json.dumps([s.to_dict() for s in screenings], indent=2, ensure_ascii=False),
    )


def get(screening_id: str) -> Screening | None:
    """The screening with this id, or None."""
    return next((s for s in load_all() if s.id == screening_id), None)


def create(fields: dict) -> Screening:
    """Create a new screening record from client-supplied editable fields."""
    now = _now()
    screening = Screening(id=new_id(), created_at=now, updated_at=now)
    _apply_editable(screening, fields)
    if screening.screening_blocker:
        # Strict here even though the store is otherwise lenient for the legacy
        # importer: this field is new and has no legacy data to tolerate, and an
        # unrecognised blocker would silently strand the record.
        screening.screening_blocker = validate_blocker(screening.screening_blocker)
    # A deferred screening is an unresolved decision, so it enters the operator's
    # approval queue. In semi-auto a *passing* one does too: the operator, not
    # the agent, decides whether to apply. A screening_blocker means the agent
    # could not even read the posting to reach a verdict — that is equally an
    # unresolved decision only the operator can settle, so it queues the same
    # way. Set here rather than accepted from `fields`: the agent's
    # record_screening reaches this function directly, and approval is not its
    # to grant.
    if screening.verdict == "deferred" or screening.screening_blocker:
        screening.approval = "pending"
    elif screening.verdict == "passed" and _agent_config_load().mode == "semi":
        screening.approval = "pending"
    with locked(screenings_path()):
        screenings = load_all()
        screenings.append(screening)
        _write_all(screenings)
    return screening


def update(screening_id: str, patch: dict) -> Screening | None:
    """Patch a screening's editable fields; returns the updated record."""
    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None:
            return None
        _apply_editable(screening, patch)
        screening.updated_at = _now()
        _write_all(screenings)
    return screening


def delete(screening_id: str) -> bool:
    """Remove a screening record and its orphaned cover-letter draft.

    Returns:
        True if the screening existed and was removed.
    """
    from coverletter import store as _coverletter_store

    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None:
            return False
        _write_all([s for s in screenings if s.id != screening_id])
    # Outside the lock: a different file, and holding one file's lock while
    # touching another is how two writers deadlock on opposite orderings.
    _coverletter_store.delete(screening_id)
    return True


def delete_many(ids: list[str]) -> list[tuple[str, bool]]:
    """Remove several screening records (and their draft letters) in one write.

    Loads the list once, writes the survivors once, and removes each deleted
    id's cover-letter draft. Unknown ids are reported False rather than
    raising, so a partially-stale selection from the client is not fatal.

    Args:
        ids: Screening ids to remove, in the order to report results.

    Returns:
        One (id, ok) pair per input id, in input order.
    """
    from coverletter import store as _coverletter_store

    with locked(screenings_path()):
        screenings = load_all()
        existing_ids = {s.id for s in screenings}
        to_delete = {i for i in ids if i in existing_ids}
        if to_delete:
            _write_all([s for s in screenings if s.id not in to_delete])
    for deleted_id in to_delete:
        _coverletter_store.delete(deleted_id)
    return [(i, i in to_delete) for i in ids]


def set_approval(screening_id: str, approval: str) -> Screening | None:
    """Set a screening's approval state — the operator's decision, never the agent's.

    Raises ValueError on an unknown state rather than writing it.
    """
    if approval not in APPROVAL_VALUES:
        raise ValueError(f"Unknown approval state '{approval}'.")
    return _mutate(screening_id, lambda s: setattr(s, "approval", approval))


def record_apply_failure(
    screening_id: str,
    error: str,
    blocker: str = "",
    signin_url: str = "",
) -> Screening | None:
    """Count one failed application attempt and keep its error for the operator.

    Leaves `approval` untouched: a failure is not a decision, and the item stays
    queued for the next run.

    `blocker` is the structured reason when there is one the app can act on —
    only "login_required" today — and `signin_url` the page to sign in at. Both
    default to empty so the original two-argument call is unchanged.
    """

    def _bump(s: Screening) -> None:
        s.apply_attempts += 1
        s.apply_error = error
        s.apply_blocker = blocker
        s.signin_url = signin_url

    return _mutate(screening_id, _bump)


def _apply_refusal(screening: Screening) -> str:
    """"" when `screening` may be applied to; a machine-readable reason otherwise.

    "already_applied" outranks everything else: an applied item is retired
    and there is nothing left to arbitrate. "contradictory_research" fires
    when the company has an unresolved contradiction in companyresearch — a
    company whose own research disagrees with itself must not be applied to
    until the operator resolves it (see companyresearch.store.resolve).

    `open_contradictions` only calls `load_all()`, which takes no lock, so
    this is safe to call from inside the screenings lock — it must stay to
    that one unlocked read and take no companyresearch lock of its own,
    since holding one file's lock while acquiring another's is how two
    writers racing in opposite orders deadlock.
    """
    if screening.approval == "applied":
        return "already_applied"
    if _open_contradictions(screening.company):
        return "contradictory_research"
    return ""


def _retire(screening_id: str) -> Screening | None:
    """Shared body for mark_applied/claim_for_apply: retire a screening if it
    may be applied to, clearing any run lease it was holding since a retired
    item is no longer anyone's work to do.

    Runs under one lock, which is what makes this a claim rather than a
    request when called via `claim_for_apply`: two concurrent callers cannot
    both succeed, so the caller that wins is the only one that may create the
    application row.
    """
    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None or _apply_refusal(screening):
            return None
        screening.approval = "applied"
        screening.claimed_by_run = ""
        screening.claim_expires_at = ""
        screening.updated_at = _now()
        _write_all(screenings)
        return screening


def mark_applied(screening_id: str) -> Screening | None:
    """Retire an approved item once its application is confirmed.

    No longer unconditional: an item whose company has an open research
    contradiction is refused here too, since the agent's own path must not
    be able to route around the same guard the REST route enforces. It
    remains unconditional with respect to *claims*: this never refuses an
    item because a different run (or no run) claimed it, because it is
    called after the ledger row is already written
    (agenttools/tools_ledger.py's record_application) — refusing here would
    lose a real submission that has already happened in the world.

    Shares its implementation with `claim_for_apply` (see `_retire`) so the
    two call paths cannot silently fork.
    """
    return _retire(screening_id)


def claim_for_apply(screening_id: str) -> Screening | None:
    """Atomically retire a screening, but only if it may be applied to.

    Returns the record on success, or None if it does not exist, was already
    ``applied``, or its company has an open research contradiction (see
    `_apply_refusal`). The check and the write happen under one lock, which
    is what makes it a claim rather than a request: two concurrent callers
    cannot both succeed, so the caller that wins is the only one that may
    create the application row.

    Shares its implementation with `mark_applied` (see `_retire`) so the two
    call paths cannot silently fork.
    """
    return _retire(screening_id)


def _claim_is_live(screening: Screening, now: str) -> bool:
    """True when `screening` is currently held by a run whose lease has not
    expired yet. An empty claimed_by_run, or a claim_expires_at at or before
    `now`, is not live — it is unclaimed and reclaimable."""
    if not screening.claimed_by_run or not screening.claim_expires_at:
        return False
    return screening.claim_expires_at > now


def claim_for_run(screening_id: str, run_id: str, lease_seconds: int) -> Screening | None:
    """Hand a screening's work to `run_id` for `lease_seconds`.

    Refuses (returns None) only when the item is currently, live-leased to a
    DIFFERENT run — an expired claim is reclaimable, which is what lets a
    crashed run's work return to the queue for the next run rather than
    being stranded forever. Claiming the same item again for the same
    run_id simply refreshes the lease.
    """
    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None:
            return None
        now = _now()
        if _claim_is_live(screening, now) and screening.claimed_by_run != run_id:
            return None
        screening.claimed_by_run = run_id
        screening.claim_expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        screening.updated_at = now
        _write_all(screenings)
        return screening


def release_claim(screening_id: str) -> Screening | None:
    """Give up a run's lease on a screening, e.g. after deciding not to apply."""
    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None:
            return None
        screening.claimed_by_run = ""
        screening.claim_expires_at = ""
        screening.updated_at = _now()
        _write_all(screenings)
        return screening


def _mutate(screening_id: str, apply) -> Screening | None:
    """Load, mutate one record outside EDITABLE, stamp, and write back."""
    with locked(screenings_path()):
        screenings = load_all()
        screening = next((s for s in screenings if s.id == screening_id), None)
        if screening is None:
            return None
        apply(screening)
        screening.updated_at = _now()
        _write_all(screenings)
    return screening


def _apply_editable(screening: Screening, fields: dict) -> None:
    """Copy only whitelisted fields."""
    for key in Screening.EDITABLE:
        if key in fields and fields[key] is not None:
            setattr(screening, key, fields[key])
