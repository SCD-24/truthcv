"""Regression tests pinning the autouse per-test data-dir isolation.

These fail if the `data_dir` fixture in tests/conftest.py is ever made
opt-in again (its autouse=True is removed).
"""

import tempfile
from pathlib import Path

import companyboards.store as company_boards_store
import truth.store

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REAL_COMPANY_BOARDS_JSON = _REPO_ROOT / "data" / "company_boards.json"


def test_data_dir_is_isolated_without_opting_in():
    """truth.store.data_dir() resolves outside the repo even for a test that never requests data_dir.

    Proves isolation is automatic (autouse), not something each test must opt into.
    """
    resolved = truth.store.data_dir().resolve()
    assert resolved != (_REPO_ROOT / "data").resolve()
    assert resolved.is_relative_to(Path(tempfile.gettempdir()).resolve())


def test_recording_a_company_board_never_touches_the_real_data_file():
    """Writing via companyboards.store.record() must not create/modify the repo's real data file."""
    existed_before = _REAL_COMPANY_BOARDS_JSON.exists()
    mtime_before = _REAL_COMPANY_BOARDS_JSON.stat().st_mtime if existed_before else None

    company_boards_store.record("Isolation Probe", "https://example.invalid")

    existed_after = _REAL_COMPANY_BOARDS_JSON.exists()
    assert existed_after == existed_before
    if existed_before:
        assert _REAL_COMPANY_BOARDS_JSON.stat().st_mtime == mtime_before
