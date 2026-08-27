"""SPA mount: index.html must never be cached, hashed assets may be."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.main as main


def _client(tmp_path, monkeypatch) -> TestClient:
    """Mount a fresh SPA over a throwaway bundle directory.

    _mount_static() resolves the module-global ``app`` and STATIC_DIR when it
    runs, so pointing both at test doubles gives a clean mount without
    disturbing the one the import already registered.
    """
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("//bundle", encoding="utf-8")
    (tmp_path / "index.html").write_text(
        '<html><script src="/assets/index-abc123.js"></script></html>', encoding="utf-8"
    )
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    fresh = FastAPI()
    monkeypatch.setattr(main, "app", fresh)
    main._mount_static()
    return TestClient(fresh)


def test_index_is_served_no_store(tmp_path, monkeypatch):
    """A cached index.html pins the browser to a stale hashed bundle."""
    r = _client(tmp_path, monkeypatch).get("/")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_explicit_index_path_is_also_no_store(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/index.html")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_hashed_asset_is_not_no_store(tmp_path, monkeypatch):
    """Assets carry a content hash in the name, so they stay cacheable."""
    r = _client(tmp_path, monkeypatch).get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "no-store" not in r.headers.get("cache-control", "")
