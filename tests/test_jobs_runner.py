"""Tests for jobs.runner: submit/get/list_jobs against the bounded pool.

Synchronization is entirely threading.Event based (no sleeps). Several tests
saturate the pool with MAX_WORKERS blocked jobs so a job of interest is
provably still queued (pending), then release exactly one worker and confirm
completion with a "sentinel" job: since only one worker is free, the
sentinel can only start once the worker that ran the job of interest has
fully returned from jobs.runner._run_job -- which is also where that job's
final status is recorded -- giving a real happens-before via Event set/wait,
not a timing guess.
"""

from __future__ import annotations

import threading
import time

import pytest

from jobs.model import STATUS_DONE, STATUS_FAILED, STATUS_PENDING, STATUS_RUNNING
from jobs.runner import MAX_RETAINED_JOBS, MAX_WORKERS, get, list_jobs, submit

_WAIT_TIMEOUT_S = 5.0


def _wait(event: threading.Event, msg: str) -> None:
    """Wait for event, failing loudly instead of hanging on a bug."""
    if not event.wait(_WAIT_TIMEOUT_S):
        pytest.fail(msg)


_STATUS_POLL_S = 5.0


def _submit_trivial(kind):
    """Submit a job whose fn sets an Event and returns; return (id, event)."""
    ran = threading.Event()

    def fn(ran=ran):
        ran.set()

    return submit(kind, fn).id, ran


def _wait_all_ran(events):
    for i, event in enumerate(events):
        _wait(event, f"burst job {i} never ran")


def _wait_all_terminal_or_evicted(ids):
    """Spin-poll (no sleep) until every id is DONE/FAILED or already evicted.

    Bridges the tiny window between a job's fn setting its "ran" Event and
    ``_run_job`` recording the terminal status a few bytecodes later.
    """
    for jid in ids:
        deadline = time.monotonic() + _STATUS_POLL_S
        while time.monotonic() < deadline:
            job = get(jid)
            if job is None or job.status in (STATUS_DONE, STATUS_FAILED):
                break
        else:
            pytest.fail(f"job {jid} never reached a terminal status")


def _burst_finished_jobs(n, kind):
    """Submit ``n`` trivial jobs, wait until each is terminal, return their ids
    in submission order (so ``created_at`` is monotonic across the list).
    """
    ids = []
    events = []
    for _ in range(n):
        jid, ran = _submit_trivial(kind)
        ids.append(jid)
        events.append(ran)
    _wait_all_ran(events)
    _wait_all_terminal_or_evicted(ids)
    return ids


def _saturate_pool():
    """Occupy every worker with a job blocked on its own release Event.

    Returns (blocker_release list) once every worker has confirmed it is
    running, so a subsequently submitted job is provably left pending.
    """
    started = [threading.Event() for _ in range(MAX_WORKERS)]
    release = [threading.Event() for _ in range(MAX_WORKERS)]

    def make_blocker(i):
        def blocker():
            started[i].set()
            release[i].wait(_WAIT_TIMEOUT_S)

        return blocker

    for i in range(MAX_WORKERS):
        submit("blocker", make_blocker(i))
    for e in started:
        _wait(e, "blocker never started")
    return release


def test_submit_runs_callable_on_a_worker_thread():
    main_thread = threading.current_thread()
    ran_event = threading.Event()
    seen = {}

    def fn():
        seen["thread"] = threading.current_thread()
        ran_event.set()
        return "ok"

    job = submit("unit-test", fn)
    _wait(ran_event, "callable never ran")
    assert seen["thread"] is not main_thread
    assert job.kind == "unit-test"
    assert job.status in (STATUS_RUNNING, STATUS_DONE)


def test_status_transitions_pending_running_done():
    blocker_release = _saturate_pool()

    target_started = threading.Event()
    target_release = threading.Event()

    def target():
        target_started.set()
        target_release.wait(_WAIT_TIMEOUT_S)
        return "target-result"

    job = submit("target", target)
    # Every worker is occupied by a blocker, so this job must still be queued.
    assert get(job.id).status == STATUS_PENDING

    blocker_release[0].set()
    _wait(target_started, "target never started")
    assert get(job.id).status == STATUS_RUNNING

    target_release.set()

    sentinel_started = threading.Event()
    submit("sentinel", lambda: sentinel_started.set())
    _wait(sentinel_started, "sentinel never started")

    assert get(job.id).status == STATUS_DONE
    assert get(job.id).result == "target-result"

    for e in blocker_release[1:]:
        e.set()


def test_failure_is_captured_into_error_and_status_failed():
    blocker_release = _saturate_pool()

    def failing():
        raise ValueError("boom")

    job = submit("failing", failing)
    assert get(job.id).status == STATUS_PENDING

    blocker_release[0].set()

    sentinel_started = threading.Event()
    submit("sentinel", lambda: sentinel_started.set())
    _wait(sentinel_started, "sentinel never started")

    assert get(job.id).status == STATUS_FAILED
    assert get(job.id).error == "boom"

    for e in blocker_release[1:]:
        e.set()


def test_get_and_list_jobs_are_thread_safe_under_concurrency():
    num_jobs = 6
    started = [threading.Event() for _ in range(num_jobs)]
    release = threading.Event()

    def make_fn(i):
        def fn():
            started[i].set()
            release.wait(_WAIT_TIMEOUT_S)
            return i

        return fn

    submitted_ids: list[str] = []
    submitted_lock = threading.Lock()

    def submit_one(i):
        job = submit(f"concurrent-{i}", make_fn(i))
        with submitted_lock:
            submitted_ids.append(job.id)

    submitters = [threading.Thread(target=submit_one, args=(i,)) for i in range(num_jobs)]
    for t in submitters:
        t.start()
    for t in submitters:
        t.join(_WAIT_TIMEOUT_S)

    assert len(submitted_ids) == num_jobs
    assert len(set(submitted_ids)) == num_jobs  # every job got a unique id

    reader_results: list[bool] = []
    reader_results_lock = threading.Lock()
    poll_rounds = 50

    def read_repeatedly():
        ok = True
        for _ in range(poll_rounds):
            ids_seen = {j.id for j in list_jobs()}
            if not set(submitted_ids).issubset(ids_seen):
                ok = False
                break
            for jid in submitted_ids:
                found = get(jid)
                if found is None or found.id != jid:
                    ok = False
                    break
        with reader_results_lock:
            reader_results.append(ok)

    readers = [threading.Thread(target=read_repeatedly) for _ in range(4)]
    for t in readers:
        t.start()
    for t in readers:
        t.join(_WAIT_TIMEOUT_S)

    assert reader_results == [True] * len(readers)

    # Unblock every job's fn so no worker is left stuck for later tests.
    release.set()


def test_submitting_past_cap_evicts_oldest_finished_survives_newest():
    # Comfortably outrun MAX_RETAINED_JOBS plus whatever finished jobs any
    # earlier test in this process may have left behind (those are strictly
    # older than everything submitted here, so they are evicted first).
    ids = _burst_finished_jobs(MAX_RETAINED_JOBS + 150, "cap-evict-burst")

    # Force one more eviction pass against the now-settled, fully-terminal
    # state so the registry is squeezed down to the cap deterministically.
    submit("evict-trigger", lambda: None)

    assert get(ids[0]) is None
    assert get(ids[-1]) is not None
    assert len(list_jobs()) <= MAX_RETAINED_JOBS


def test_pending_and_running_jobs_are_never_evicted_even_over_cap():
    # Push well past the cap with finished jobs first, while every worker is
    # free to actually run and finish them.
    _burst_finished_jobs(MAX_RETAINED_JOBS + 50, "cap-pending-burst")

    # Saturate every worker with a job blocked on its own release Event:
    # these are RUNNING and must never be evicted, however far over cap the
    # registry has been pushed.
    started = [threading.Event() for _ in range(MAX_WORKERS)]
    release = [threading.Event() for _ in range(MAX_WORKERS)]

    def make_blocker(i):
        def blocker():
            started[i].set()
            release[i].wait(_WAIT_TIMEOUT_S)

        return blocker

    running_ids = [submit("held-running", make_blocker(i)).id for i in range(MAX_WORKERS)]
    for e in started:
        _wait(e, "blocker never started")
    for jid in running_ids:
        assert get(jid).status == STATUS_RUNNING

    # With every worker now busy, these queue up PENDING behind the
    # blockers -- each submit() call above and below also runs an eviction
    # pass, which must skip both sets entirely.
    pending_ids = [submit("queued-behind-blockers", lambda: None).id for _ in range(3)]
    for jid in pending_ids:
        assert get(jid).status == STATUS_PENDING

    for jid in [*running_ids, *pending_ids]:
        job = get(jid)
        assert job is not None
        assert job.status in (STATUS_PENDING, STATUS_RUNNING)

    for e in release:
        e.set()


def test_registry_stays_at_or_under_cap_after_a_burst_of_finished_jobs():
    _burst_finished_jobs(MAX_RETAINED_JOBS + 75, "cap-burst")

    # One more submit forces a final eviction pass against fully-settled
    # state so the cap holds exactly, not just "close to" the limit.
    submit("evict-trigger-2", lambda: None)

    assert len(list_jobs()) <= MAX_RETAINED_JOBS
