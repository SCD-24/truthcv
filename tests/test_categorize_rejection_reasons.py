"""scripts/categorize_rejection_reasons.py: dry run, apply, idempotence."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import screening.store as store

_SPEC = importlib.util.spec_from_file_location(
    "categorize_rejection_reasons",
    Path(__file__).resolve().parent.parent / "scripts" / "categorize_rejection_reasons.py",
)
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


@pytest.fixture
def seeded(data_dir):
    """Rejected records with legacy raw values, plus a deferred and a None one."""
    raws = ["1. Fully remote", "remote_model", "qwertyuiop", None]
    for i, _ in enumerate(raws):
        store.create({"company": f"Co{i}", "role": "Engineer", "verdict": "rejected"})
    store.create(
        {"company": "Def", "role": "Engineer", "verdict": "deferred"}
    )
    records = store.load_all()
    for rec, raw in zip(records, raws + ["glassdoor_rating"]):
        rec.failing_criterion = raw
    store._write_all(records)
    return raws


def _values():
    return [s.failing_criterion for s in store.load_all()]


def test_dry_run_writes_nothing(seeded, capsys):
    assert script.main([]) == 0
    assert _values() == seeded + ["glassdoor_rating"]
    out = capsys.readouterr().out
    assert "to-normalize: 3" in out
    assert "skipped (not rejected): 1" in out


def test_apply_rewrites_only_rejected_non_canonical(seeded):
    before = {s.id: s.updated_at for s in store.load_all()}
    script.main(["--apply"])
    assert _values() == ["remote_model", "remote_model", "other", "", "glassdoor_rating"]
    after = {s.id: s.updated_at for s in store.load_all()}
    canonical_id = store.load_all()[1].id
    deferred_id = store.load_all()[4].id
    assert after[canonical_id] == before[canonical_id]
    assert after[deferred_id] == before[deferred_id]


def test_report_counts_include_canonical(seeded, capsys):
    script.main([])
    assert "  remote_model: 2" in capsys.readouterr().out


def test_second_apply_changes_nothing(seeded, capsys):
    script.main(["--apply"])
    snapshot = [(s.id, s.failing_criterion, s.updated_at) for s in store.load_all()]
    capsys.readouterr()
    script.main(["--apply"])
    assert [(s.id, s.failing_criterion, s.updated_at) for s in store.load_all()] == snapshot
    assert "to-normalize: 0" in capsys.readouterr().out
