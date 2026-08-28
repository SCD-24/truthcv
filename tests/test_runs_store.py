"""runs/store.py: lifecycle, retention, corruption-safety, and lock safety."""

from __future__ import annotations

import json
import threading

from runs import store
from agenttools import tools_runs


def test_start_bump_finish_lifecycle(data_dir):
    record = store.start("run-1", trigger="scheduled", apply_cap=5)
    assert record.status == "running"
    assert record.apply_cap == 5
    assert record.started_at

    bumped = store.bump("run-1", postings_seen=3, screenings_recorded=2)
    assert bumped.postings_seen == 3
    assert bumped.screenings_recorded == 2

    bumped_again = store.bump("run-1", postings_seen=1)
    assert bumped_again.postings_seen == 4

    finished = store.finish("run-1", status="completed", stopped_reason="", note="done")
    assert finished.status == "completed"
    assert finished.finished_at
    assert finished.note == "done"

    fetched = store.get("run-1")
    assert fetched.status == "completed"
    assert fetched.postings_seen == 4


def test_start_is_idempotent(data_dir):
    first = store.start("run-2", trigger="scheduled", apply_cap=5)
    store.bump("run-2", postings_seen=9)
    second = store.start("run-2", trigger="manual", apply_cap=999)
    assert second.postings_seen == 9
    assert second.trigger == "scheduled"
    assert second.apply_cap == 5


def test_list_recent_orders_newest_first_and_honours_limit(data_dir):
    for i in range(5):
        r = store.start(f"run-{i}", trigger="scheduled", apply_cap=0)
        # started_at is identical-ish; force distinct ordering deterministically.
        all_runs = store.load_all()
        for rec in all_runs:
            if rec.id == r.id:
                rec.started_at = f"2024-01-0{i + 1}T00:00:00+00:00"
        store._write_all(all_runs)

    recent = store.list_recent(limit=3)
    assert [r.id for r in recent] == ["run-4", "run-3", "run-2"]


def _dated_runs(count: int) -> None:
    """Record `count` runs with distinct, ascending started_at values."""
    for i in range(count):
        store.start(f"run-{i}", trigger="scheduled", apply_cap=0)
    all_runs = store.load_all()
    by_id = {r.id: r for r in all_runs}
    for i in range(count):
        by_id[f"run-{i}"].started_at = f"2024-01-{i + 1:02d}T00:00:00+00:00"
    store._write_all(all_runs)


def test_offset_pages_backwards_through_history(data_dir):
    _dated_runs(12)
    assert [r.id for r in store.list_recent(limit=5, offset=0)] == [
        "run-11", "run-10", "run-9", "run-8", "run-7",
    ]
    assert [r.id for r in store.list_recent(limit=5, offset=5)] == [
        "run-6", "run-5", "run-4", "run-3", "run-2",
    ]
    # Last page is short, not padded.
    assert [r.id for r in store.list_recent(limit=5, offset=10)] == ["run-1", "run-0"]


def test_pages_do_not_overlap_or_skip(data_dir):
    """The property that matters to a reader paging through: every run appears
    exactly once across the pages, in order."""
    _dated_runs(12)
    seen = []
    for offset in range(0, 12, 5):
        seen.extend(r.id for r in store.list_recent(limit=5, offset=offset))
    assert seen == [f"run-{i}" for i in range(11, -1, -1)]


def test_offset_past_the_end_is_an_empty_page_not_an_error(data_dir):
    _dated_runs(3)
    assert store.list_recent(limit=5, offset=99) == []


def test_offset_is_applied_before_the_limit(data_dir):
    """Applying the limit first would page through the same five runs forever."""
    _dated_runs(12)
    first = store.list_recent(limit=5, offset=0)
    second = store.list_recent(limit=5, offset=5)
    assert not ({r.id for r in first} & {r.id for r in second})


def test_no_limit_still_means_everything(data_dir):
    """Callers that want the whole history pass limit=0; offset must not have
    quietly turned that into a page."""
    _dated_runs(7)
    assert len(store.list_recent(limit=0)) == 7


def test_count_is_the_total_not_a_page(data_dir):
    _dated_runs(12)
    assert store.count() == 12
    assert len(store.list_recent(limit=5)) == 5


def test_retention_caps_at_200_records(data_dir):
    for i in range(210):
        store.start(f"r{i}", trigger="scheduled", apply_cap=0)
    all_runs = store.load_all()
    assert len(all_runs) == 200


def test_missing_file_yields_empty_list(data_dir):
    assert store.load_all() == []


def test_corrupt_file_yields_empty_list(data_dir):
    store.runs_path().parent.mkdir(parents=True, exist_ok=True)
    store.runs_path().write_text("{not json", encoding="utf-8")
    assert store.load_all() == []


def test_non_list_payload_yields_empty_list(data_dir):
    store.runs_path().parent.mkdir(parents=True, exist_ok=True)
    store.runs_path().write_text(json.dumps({"oops": True}), encoding="utf-8")
    assert store.load_all() == []


def test_concurrent_bumps_do_not_lose_a_record(data_dir):
    store.start("race", trigger="scheduled", apply_cap=0)

    def do_bump():
        store.bump("race", postings_seen=1)

    threads = [threading.Thread(target=do_bump) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert store.get("race").postings_seen == 20


def test_tools_no_op_on_empty_run_id():
    assert tools_runs.start_run(run_id="") == {"recorded": False}
    assert tools_runs.finish_run(run_id="") == {"recorded": False}
    assert tools_runs.record_run_note(run_id="", note="x") == {"recorded": False}
    assert tools_runs.bump_run_counters(run_id="", postings_seen=1) == {"recorded": False}


def test_start_run_tool_is_idempotent(data_dir):
    first = tools_runs.start_run(run_id="run-tool", trigger="scheduled", apply_cap=3)
    assert first["recorded"] is True
    tools_runs.bump_run_counters(run_id="run-tool", postings_seen=5)
    second = tools_runs.start_run(run_id="run-tool", trigger="manual", apply_cap=999)
    assert second["recorded"] is True
    assert second["postings_seen"] == 5
    assert second["apply_cap"] == 3


def test_finish_if_running_closes_a_record_the_agent_never_finished(data_dir):
    """The case this exists for: a run that died before the model's first turn.

    The host side created the record, the model never got far enough to call
    finish_run, and without this the record would sit at "running" forever.
    """
    store.start("crashed", trigger="manual")
    record = store.finish_if_running(
        "crashed", status="failed", stopped_reason="the LLM provider rejected every attempt"
    )
    assert record is not None
    assert record.status == "failed"
    assert record.stopped_reason == "the LLM provider rejected every attempt"
    assert record.finished_at


def test_finish_if_running_never_overwrites_the_agents_own_account(data_dir):
    """The model's finish_run names where the run actually stopped; the
    supervisor's exit-code summary is a fallback and must not replace it."""
    store.start("honest", trigger="scheduled")
    store.finish("honest", status="completed", stopped_reason="apply cap reached")

    assert store.finish_if_running("honest", status="failed", stopped_reason="exit 3") is None

    record = store.get("honest")
    assert record.status == "completed"
    assert record.stopped_reason == "apply cap reached"


def test_finish_if_running_is_a_no_op_for_an_unknown_run(data_dir):
    assert store.finish_if_running("never-started", status="failed") is None
    assert store.get("never-started") is None


def test_a_negative_offset_reads_from_the_newest_not_the_end(data_dir):
    """A negative index into a Python list reads from the END, so an unguarded
    slice would answer a paged-past-the-start client with the OLDEST runs while
    calling them the newest. The route clamps too; this pins the store's own
    guard, which nothing else was testing."""
    _dated_runs(3)
    assert [r.id for r in store.list_recent(limit=2, offset=-5)] == ["run-2", "run-1"]


def test_list_page_returns_the_page_and_the_total_it_came_from(data_dir):
    _dated_runs(12)

    page, total = store.list_page(limit=5, offset=5)

    assert [r.id for r in page] == ["run-6", "run-5", "run-4", "run-3", "run-2"]
    assert total == 12


def test_list_page_totals_everything_even_when_the_page_is_empty(data_dir):
    _dated_runs(3)

    page, total = store.list_page(limit=5, offset=99)

    assert page == []
    assert total == 3


def test_list_page_with_no_limit_returns_everything(data_dir):
    _dated_runs(7)

    page, total = store.list_page(limit=0)

    assert len(page) == 7
    assert total == 7
