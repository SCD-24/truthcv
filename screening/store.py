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
from storage import atomic_write_text, locked
from storage import data_dir

from .model import APPROVAL_VALUES, Screening, new_id, validate_blocker
from .url import posting_dedupe_key

# screening_blocker values that stay operator-actionable: the operator can sign
# in themselves (login_required) or paste the posting text back in
# (unreadable). 'not_found' and 'expired' are deliberately excluded — there is
# no decision to make and nothing to draft from a posting that no longer
# exists, so those records must not reach the approval queue.
QUEUEING_BLOCKERS = ("login_required", "unreadable")

# screening_blocker values describing a posting that was never evaluated and
# never put to the operator either: the agent saw a dead link or an expired
# listing, and (being outside QUEUEING_BLOCKERS) the record did not queue. A
# record like that holds no judgement, so it must not permanently suppress a
# re-screen the way a real verdict does — a board that 404s for an afternoon
# would otherwise blacklist a live posting that nobody ever sees again. See
# `_is_unread_placeholder`.
UNREAD_BLOCKERS = ("not_found", "expired")


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


def find_by_url(url: str) -> Screening | None:
    """The existing screening for the posting ``url`` names, or None.

    Matches on ``posting_dedupe_key`` rather than the raw string, so the same
    job arriving from a board listing, a job alert and a direct link is one
    posting. A blank or unparseable ``url`` has an empty key and matches
    nothing — two records the store could not resolve to a posting are not
    thereby the same posting.
    """
    key = posting_dedupe_key(url)
    if not key:
        return None
    return _find_by_key(load_all(), key)


def _find_by_key(screenings: list[Screening], key: str) -> Screening | None:
    """First record in ``screenings`` whose url has dedupe key ``key``.

    Split out so ``create_or_get`` can run the lookup against the list it
    already loaded inside the lock, instead of re-reading the file.
    """
    return next((s for s in screenings if posting_dedupe_key(s.url) == key), None)


def _is_unread_placeholder(screening: Screening) -> bool:
    """Whether ``screening`` may be superseded by a fresh screening of the same
    posting.

    True only for a record that holds nothing anyone could lose: the agent
    could not read the posting at all (an UNREAD_BLOCKERS blocker), the
    operator was never asked and never decided (`approval` empty), and no
    application attempt or run claim was ever made against it. Those last two
    are already implied by the empty approval — only an approved item is
    handed out or attempted — and are checked anyway, because this function's
    caller overwrites the record and the cost of being wrong is a lost
    application attempt.
    """
    return (
        screening.screening_blocker in UNREAD_BLOCKERS
        and not screening.approval
        and not screening.apply_attempts
        and not screening.claimed_by_run
    )


def create_or_get(fields: dict) -> tuple[Screening, bool]:
    """Create a screening, or return the one this posting already has.

    Returns ``(record, created)``. ``created`` is False when the store already
    held a record for this posting URL, in which case that record is returned
    untouched, nothing is written, and the screening passed in is discarded.

    The one exception is an unread placeholder — a dead-link or expired-listing
    blocker nobody was ever asked about (``_is_unread_placeholder``) — which is
    overwritten in place by the new screening, keeping the original record's id
    and created_at. It is still ``created=False``: no record was added. This is
    what stops a board that 404s for an afternoon from permanently suppressing
    a live posting, which would be invisible because such records never queue.

    One posting, one record — forever, whatever either record's verdict or
    approval says. That is the point: an operator who rejected a posting had
    the same posting re-screened and re-queued on every subsequent run,
    because the operator's rejection is recorded as ``approval`` on one record
    and nothing anywhere compared URLs. Enforced here, at the single write
    path all three callers share (the agent's ``record_screening``, ``POST
    /api/screenings``, and the historical importer), so no caller can route
    around it.

    The lookup and the append happen under one lock, which is what makes this
    a claim rather than a request: two runs recording the same posting at the
    same moment cannot both create a record.

    Deleting a screening is the deliberate escape hatch — it drops the record
    and with it the block, so a posting genuinely re-listed under the same URL
    can be screened again.
    """
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
    # way, but only when the blocker is one the operator can actually act on
    # (QUEUEING_BLOCKERS): 'not_found' and 'expired' describe a posting that no
    # longer exists, so there is nothing for the operator to decide or draft
    # from and the record must not queue. Set here rather than accepted from
    # `fields`: the agent's record_screening reaches this function directly,
    # and approval is not its to grant.
    if screening.verdict == "deferred" or screening.screening_blocker in QUEUEING_BLOCKERS:
        screening.approval = "pending"
    elif screening.verdict == "passed" and _agent_config_load().mode == "semi":
        screening.approval = "pending"
    key = posting_dedupe_key(screening.url)
    with locked(screenings_path()):
        screenings = load_all()
        if key:
            existing = _find_by_key(screenings, key)
            if existing is not None:
                if not _is_unread_placeholder(existing):
                    return existing, False
                # Supersede: the new screening takes the old record's identity
                # so nothing referring to it by id is orphaned, and keeps the
                # run that first recorded the posting when this call names
                # none. Every other field on `existing` is a default —
                # `_is_unread_placeholder` established that — so replacing the
                # record wholesale loses nothing.
                screening.id = existing.id
                screening.created_at = existing.created_at
                screening.run_id = screening.run_id or existing.run_id
                screenings[screenings.index(existing)] = screening
                _write_all(screenings)
                return screening, False
        screenings.append(screening)
        _write_all(screenings)
    return screening, True


def create(fields: dict) -> Screening:
    """Create a new screening record from client-supplied editable fields.

    Delegates to ``create_or_get`` and discards the created flag: a caller
    that needs to tell a fresh record from an existing one for this posting
    must call that instead.
    """
    return create_or_get(fields)[0]


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


def clear_apply_failure(screening_id: str) -> Screening | None:
    """Clear a stale apply failure's operator-facing text.

    Empties `apply_error`, `apply_blocker`, and `signin_url` only. This is an
    operator action taken when the recorded failure no longer applies — e.g.
    the environment fault that caused it (not a fact about the posting or the
    operator's application) has since been fixed — not a verdict about the
    screening itself, so `approval`, `apply_attempts`, and claim fields are
    left untouched: the attempt count is kept deliberately, as history of how
    many times this item has actually been tried.
    """

    def _clear(s: Screening) -> None:
        s.apply_error = ""
        s.apply_blocker = ""
        s.signin_url = ""

    return _mutate(screening_id, _clear)


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
    """Copy only whitelisted fields.

    run_id is write-once: it is the durable record of which agent run produced
    this screening, and the run's derived coverage counters are computed from
    it, so a later edit must not reassign or blank it once it is set.
    """
    for key in Screening.EDITABLE:
        if key not in fields or fields[key] is None:
            continue
        if key == "run_id" and screening.run_id:
            continue
        setattr(screening, key, fields[key])
