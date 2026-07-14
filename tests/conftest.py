"""Shared fixtures: isolate the data volume per test."""

from __future__ import annotations

import pytest


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir so tests never touch the real ./data."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path
