"""Bounded background job runner: a shared thread pool plus an in-memory,
thread-safe registry of :class:`jobs.model.Job` records.

Callers submit a zero-argument callable via :func:`submit`; it runs on a
worker thread and its outcome (result or exception) is recorded onto the
returned ``Job``. :func:`get` and :func:`list_jobs` poll that state.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .model import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    Job,
)

logger = logging.getLogger(__name__)

# Bounded pool size: caps how many jobs (e.g. Gmail syncs, feed refreshes)
# can run at once so a burst of requests cannot spawn unbounded threads.
MAX_WORKERS = 4

# Bounded registry size: nothing ever removes a finished job from ``_jobs``
# on its own, so a long-running server would otherwise accumulate an
# unbounded number of done/failed records. Once the registry grows past this
# many entries, submit() evicts the oldest finished/failed jobs (never
# pending/running ones) until it is back at or under the cap.
MAX_RETAINED_JOBS = 200

_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="job-runner")
_lock = threading.Lock()
_jobs: dict[str, Job] = {}


def submit(kind: str, fn: Callable[[], Any]) -> Job:
    """Submit a zero-argument callable as a background job.

    Returns immediately with a ``Job`` record in ``pending`` status; the
    callable is handed to the shared bounded executor and will transition
    the record to ``running`` and then ``done``/``failed`` as it executes.
    """
    if not kind or not isinstance(kind, str):
        raise ValueError("kind must be a non-empty string")
    if not callable(fn):
        raise ValueError("fn must be callable")

    job = Job(id=str(uuid.uuid4()), kind=kind, status=STATUS_PENDING)
    with _lock:
        _jobs[job.id] = job
        evicted = _evict_oldest_finished_locked()

    # Log outside the critical section (matching "job submitted" below) so a
    # slow logging handler can never stall other threads on the registry lock.
    for stale_id, stale_kind, stale_status in evicted:
        logger.info(
            "job evicted",
            extra={"job_id": stale_id, "job_kind": stale_kind, "job_status": stale_status},
        )
    logger.info("job submitted", extra={"job_id": job.id, "job_kind": job.kind})
    _executor.submit(_run_job, job, fn)
    return job


def _evict_oldest_finished_locked() -> list[tuple[str, str, str]]:
    """Evict the oldest finished/failed jobs until the registry fits the cap.

    Must be called with ``_lock`` already held. Only STATUS_DONE and
    STATUS_FAILED jobs are ever evicted; pending/running jobs are always
    kept, so the registry may transiently exceed MAX_RETAINED_JOBS while
    many jobs are in flight at once. Returns ``(id, kind, status)`` for each
    evicted job so the caller can log them after releasing the lock.
    """
    if len(_jobs) <= MAX_RETAINED_JOBS:
        return []
    evictable = sorted(
        (j for j in _jobs.values() if j.status in (STATUS_DONE, STATUS_FAILED)),
        key=lambda j: j.created_at,
    )
    evicted: list[tuple[str, str, str]] = []
    for stale in evictable:
        if len(_jobs) <= MAX_RETAINED_JOBS:
            break
        del _jobs[stale.id]
        evicted.append((stale.id, stale.kind, stale.status))
    return evicted


def get(job_id: str) -> Job | None:
    """Return the ``Job`` record for ``job_id``, or ``None`` if unknown."""
    if not job_id or not isinstance(job_id, str):
        raise ValueError("job_id must be a non-empty string")
    with _lock:
        return _jobs.get(job_id)


def list_jobs() -> list[Job]:
    """Return a snapshot list of every known job, in no particular order."""
    with _lock:
        return list(_jobs.values())


def job_to_dict(job: Job) -> dict:
    """Serialize ``job`` to a plain dict under the registry lock.

    Workers mutate ``status``/``result``/``error`` together under ``_lock``;
    serializing under that same lock guarantees a consistent snapshot (never
    ``status == "done"`` with ``result`` still unset)."""
    with _lock:
        return dataclasses.asdict(job)


def _run_job(job: Job, fn: Callable[[], Any]) -> None:
    """Execute ``fn`` on the current worker thread and record the outcome.

    Runs entirely on the pool's worker thread; the worker is only free to
    pick up its next queued job once this function returns, so ``job``'s
    final status is always set before that happens.
    """
    with _lock:
        job.status = STATUS_RUNNING
        job.started_at = time.time()
    logger.info("job started", extra={"job_id": job.id, "job_kind": job.kind})

    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - deliberately capture any failure
        with _lock:
            job.status = STATUS_FAILED
            job.error = str(exc)
            job.finished_at = time.time()
        logger.exception(
            "job failed", extra={"job_id": job.id, "job_kind": job.kind}
        )
        return

    with _lock:
        job.status = STATUS_DONE
        job.result = result
        job.finished_at = time.time()
    logger.info("job done", extra={"job_id": job.id, "job_kind": job.kind})
