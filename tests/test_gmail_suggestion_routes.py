"""Gmail suggestion routes: list pending and dismiss."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import secretstore
from api.main import app
from gmailsync.model import GmailSuggestion
from gmailsync.store import save_suggestions

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="
URL = "/api/gmail/suggestions"


@pytest.fixture()
def client(data_dir, monkeypatch):
    """TestClient with an encryption key and no env-provided Jev key."""
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)
    monkeypatch.delenv("JEV_API_KEY", raising=False)
    return TestClient(app)


def _open_gate() -> None:
    """Open the Gmail tracking gate."""
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForEmailTracking": True})


def _s(sid: str, state: str = "pending", date: str = "2024-01-01") -> GmailSuggestion:
    """Build a suggestion."""
    return GmailSuggestion(id=sid, state=state, date=date)


def test_gate_closed_is_403(client):
    """Both routes 403 when the gate is closed."""
    assert client.get(URL).status_code == 403
    assert client.post(URL + "/dismiss", json={"ids": ["a"]}).status_code == 403


def test_list_pending_newest_first_with_paging(client):
    """Only pending, newest first, with total and limit/offset."""
    _open_gate()
    save_suggestions([
        _s("old", date="2024-01-01"),
        _s("new", date="2024-03-01"),
        _s("mid", date="2024-02-01"),
        _s("done", "dismissed", date="2024-04-01"),
    ])
    body = client.get(URL).json()
    assert [i["id"] for i in body["items"]] == ["new", "mid", "old"]
    assert body["total"] == 3
    page = client.get(URL, params={"limit": 1, "offset": 1}).json()
    assert [i["id"] for i in page["items"]] == ["mid"]
    assert page["total"] == 3


def test_limit_over_max_is_422(client):
    """limit above the maximum is rejected."""
    _open_gate()
    assert client.get(URL, params={"limit": 101}).status_code == 422


def test_dismiss_returns_counts(client):
    """Dismiss flips pending and reports remaining pending."""
    _open_gate()
    save_suggestions([_s("a"), _s("b")])
    resp = client.post(URL + "/dismiss", json={"ids": ["a"]})
    assert resp.status_code == 200
    assert resp.json() == {"dismissed": 1, "pending": 1}


def test_dismiss_empty_ids_is_422(client):
    """Empty ids list is rejected."""
    _open_gate()
    assert client.post(URL + "/dismiss", json={"ids": []}).status_code == 422
