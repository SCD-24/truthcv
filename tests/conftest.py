"""Shared fixtures: isolate the data volume per test."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir so tests never touch the real ./data.

    Autouse: isolation now applies to every test automatically. Tests that
    need the temp path as a value can still request it explicitly (directly
    or via wrapper fixtures) and will receive this same per-test instance.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path
