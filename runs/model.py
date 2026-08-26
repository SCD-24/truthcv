"""Data shape for one agent run record.

A RunRecord is the durable, honest account of one execution of the
unattended job-application agent: when it started and finished, how it
ended, and how much of the work it actually covered. It exists so a run
that stops early — crash, cap reached, cancelled — leaves behind a truthful
summary instead of silence. Modelled on screening/model.py.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

STATUS_VALUES = ("running", "completed", "cancelled", "failed")


def validate_status(status: str) -> str:
    """Return the status lowercased, or raise ``ValueError`` if not a known one."""
    cleaned = status.strip().casefold() if isinstance(status, str) else ""
    if cleaned not in STATUS_VALUES:
        raise ValueError(
            f"Unknown run status {status!r}. Use one of: {', '.join(STATUS_VALUES)}."
        )
    return cleaned


@dataclass
class RunRecord:
    """One execution of the unattended job-application agent."""

    # The run's identity, minted by the supervisor and threaded through every
    # tool call the agent makes during this run.
    id: str = ""
    # UTC ISO-8601 timestamp of when the run began.
    started_at: str = ""
    # UTC ISO-8601 timestamp of when the run ended; empty while still running.
    finished_at: str = ""
    # One of STATUS_VALUES: "running" until finish() is called.
    status: str = ""
    # What started this run: e.g. "scheduled" or "manual".
    trigger: str = ""
    # The per-run application cap in effect, resolved at start (0 = uncapped).
    apply_cap: int = 0
    # How many postings the agent looked at this run.
    postings_seen: int = 0
    # How many screening records the agent wrote this run.
    screenings_recorded: int = 0
    # How many postings the agent could not read (screening_blocker set).
    blocked_count: int = 0
    # How many applications were actually submitted this run.
    applications_submitted: int = 0
    # How many of this run's screenings landed in the operator's approval
    # queue (approval == "pending") — the outcome that matters for a SEMI-AUTO
    # run, which submits nothing by design and so would otherwise have no
    # number describing what it achieved.
    queued_for_approval: int = 0
    # Submissions that arrived for an item this run had not claimed — flagged,
    # never refused, because the form was already submitted in the real world.
    over_cap_writes: int = 0
    # The coverage answer: where a partial run stopped, in the agent's own
    # words (e.g. "apply cap reached", "browser session died"). Empty for a
    # run that completed normally.
    stopped_reason: str = ""
    # Free-text note the agent can leave via record_run_note.
    note: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "RunRecord":
        known = {f for f in cls.__dataclass_fields__}
        values = {k: raw[k] for k in known if k in raw}
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


def new_id() -> str:
    """Short, filename-safe run id."""
    import uuid

    return uuid.uuid4().hex[:12]
