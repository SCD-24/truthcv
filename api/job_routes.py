"""FastAPI routes for triggering and polling background jobs (jobs.runner).

Runnable job kinds are declared in ``_JOB_KINDS``: each maps a URL segment to
an optional synchronous guard (run before accepting the job, so a gate like
``require_gmail_tracking_enabled`` still 403s immediately instead of failing
the job asynchronously) and the zero-argument callable jobs.runner executes
on a worker thread. Adding a new kind means adding one entry there.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

import jobs
from jobs.model import Job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs")

# HTTP status for "job accepted, not yet complete" (RFC 7231 202).
_STATUS_ACCEPTED = 202


def _run_gmail_sync() -> dict:
    """Run a Gmail response-tracking sync (same operation as
    POST /api/gmail/responses/sync, without the optional ``force`` flag)."""
    from gmailsync import service as gmailsync_service

    return gmailsync_service.run_sync(force=False)


def _guard_gmail_sync() -> None:
    """Reuse the exact gate the existing Gmail sync route enforces."""
    from api.routes import require_gmail_tracking_enabled

    require_gmail_tracking_enabled()


def _run_feed_refresh() -> dict:
    """Pull postings for the configured API-backed boards.

    Same operation GET /api/agent/config?include_feed=true performs inline;
    reuses that route's own helpers so the two never drift apart.
    """
    from agentconfig import store as agent_config_store
    from api.routes import _fetch_feed_postings, _target_company_boards

    cfg = agent_config_store.load()
    target_boards = _target_company_boards(cfg)
    feed = _fetch_feed_postings(cfg, target_boards)
    return {"postings": [p.to_dict() for p in feed.postings], "error": feed.error}


# kind -> (optional synchronous guard, zero-argument runnable).
_JOB_KINDS: dict[str, tuple[Callable[[], None] | None, Callable[[], Any]]] = {
    "gmail-sync": (_guard_gmail_sync, _run_gmail_sync),
    "feed-refresh": (None, _run_feed_refresh),
}


def _job_to_dict(job: Job) -> dict:
    """Serialize a Job record to a plain JSON-able dict.

    Delegates to ``jobs.job_to_dict`` so the snapshot is taken under the
    registry lock — a worker thread setting status/result together can never
    be observed half-applied (e.g. ``done`` with a null result)."""
    return jobs.job_to_dict(job)


@router.get("")
def list_all_jobs() -> list[dict]:
    """List every known job with its current status."""
    return [_job_to_dict(job) for job in jobs.list_jobs()]


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    """Fetch one job's status/result by id. 404s for an unknown id."""
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _job_to_dict(job)


@router.post("/{kind}", status_code=_STATUS_ACCEPTED)
def start_job(kind: str) -> dict:
    """Start a background job of the given kind. 404s for an unknown kind.

    Any registered guard runs synchronously before the job is accepted, so
    a disabled feature (e.g. Gmail tracking) still fails the request
    immediately rather than the job silently landing in ``failed``.
    """
    entry = _JOB_KINDS.get(kind)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown job kind '{kind}'.")
    guard, runnable = entry
    if guard is not None:
        guard()
    return _job_to_dict(jobs.submit(kind, runnable))
