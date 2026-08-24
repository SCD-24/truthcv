"""The operator's on-demand cover letter: generate, read, edit, save.

Generation is guardrailed exactly as the agent's is. Saving an edit is NOT: the
operator is the source of the truth document, so a claim they type is one they
are asserting on their own behalf. That asymmetry is the point of these routes
and is asserted below.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import coverletter.store as letters
import screening.store as store
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _queued(posting_text="Staff AI Engineer, Germany (Remote). Python, LLMs."):
    return store.create(
        {
            "company": "Grafana Labs",
            "role": "Staff AI Engineer",
            "verdict": "deferred",
            "posting_text": posting_text,
        }
    )


class _StubProvider:
    """Returns one paragraph with an empty ``claims`` list. The guardrail only
    validates a paragraph's self-tagged claims (coverletter/generate.py's
    ``_letter_scope`` builds its Scope from ``claims``, never from ``text``),
    so an empty claims list clears validation regardless of the prose. Keeps
    these tests off the network."""

    def extract_json(self, system, messages, schema=None):
        return {"paragraphs": [{"text": "It is the work that was created.", "claims": []}]}


@pytest.fixture()
def stub_provider(monkeypatch):
    import agenttools.tools_letter as tools_letter

    monkeypatch.setattr(tools_letter, "get_provider", lambda _name: _StubProvider())
    return _StubProvider()


def test_get_letter_404_when_none(client):
    s = _queued()
    assert client.get(f"/api/screenings/{s.id}/letter").status_code == 404


def test_generate_writes_a_generated_draft(client, stub_provider):
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 200
    assert r.json()["source"] == "generated"
    assert r.json()["text"]
    assert letters.load(s.id).source == "generated"


def test_generate_404_on_unknown_screening(client, stub_provider):
    assert client.post("/api/screenings/nope/letter", json={}).status_code == 404


def test_generate_409_without_posting_text(client, stub_provider):
    """Every imported screening is in this state — there is nothing to draft
    from, and the UI must say so rather than offer a button that cannot work."""
    s = _queued(posting_text="")
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 409
    assert "posting" in r.json()["detail"].lower()


def test_save_stores_operator_text_verbatim(client):
    s = _queued()
    r = client.put(
        f"/api/screenings/{s.id}/letter",
        json={"text": "I personally shipped the thing, unverifiably."},
    )
    assert r.status_code == 200
    assert r.json()["source"] == "operator"
    assert r.json()["text"] == "I personally shipped the thing, unverifiably."
    assert client.get(f"/api/screenings/{s.id}/letter").json()["text"] == (
        "I personally shipped the thing, unverifiably."
    )


def test_save_404_on_unknown_screening(client):
    assert client.put("/api/screenings/nope/letter", json={"text": "x"}).status_code == 404


def test_save_empty_text_422(client):
    """Blanking is not an edit; the operator's only path to no-draft is never
    writing one, or letting regenerate replace it."""
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.put(f"/api/screenings/{s.id}/letter", json={"text": ""})
    assert r.status_code == 422
    assert letters.load(s.id).text == "Mine."


def test_save_whitespace_only_text_422(client):
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.put(f"/api/screenings/{s.id}/letter", json={"text": "   "})
    assert r.status_code == 422
    assert letters.load(s.id).text == "Mine."


def test_regenerate_refuses_over_an_operator_draft(client, stub_provider):
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 409
    assert letters.load(s.id).text == "Mine."


def test_regenerate_with_force_replaces_an_operator_draft(client, stub_provider):
    s = _queued()
    client.put(f"/api/screenings/{s.id}/letter", json={"text": "Mine."})
    r = client.post(f"/api/screenings/{s.id}/letter", json={"force": True})
    assert r.status_code == 200
    assert r.json()["source"] == "generated"
    assert letters.load(s.id).text != "Mine."


def test_blocked_generation_writes_nothing_and_names_the_claims(client, monkeypatch):
    """The guardrail still binds on generation. A blocked letter must not be
    stored: a draft on disk is what unlocks Approve, so storing a blocked one
    would let an ungrounded claim through the one gate that catches it."""
    import agenttools.tools_letter as tools_letter

    class _Overclaiming:
        def extract_json(self, system, messages, schema=None):
            return {
                "paragraphs": [
                    {
                        "text": "I personally invented Kubernetes at Grafana Labs.",
                        "claims": ["invented Kubernetes"],
                    }
                ]
            }

    monkeypatch.setattr(tools_letter, "get_provider", lambda _name: _Overclaiming())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 422
    assert letters.load(s.id) is None


def test_generate_422_when_company_is_blocklisted(client, stub_provider):
    """The blocklist short-circuits before the model is ever called (see
    agenttools/tools_letter.py's is_blocked check), returning the same
    blocked=True shape as a guardrail rejection. That path is untested at
    the route layer even though it's safe by inspection, so exercise it
    directly: nothing should be written to the letter store either."""
    import agentconfig.store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = ["Grafana Labs"]
    agent_config_store.save(cfg)

    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 422
    assert r.json()["detail"]["blockedReason"] == "company_blocked"
    assert letters.load(s.id) is None


def test_letter_routes_are_outside_the_agent_prefix(client):
    """The agent authenticates only against /api/agent/*. Nothing it can reach
    may write a letter the operator is meant to own."""
    for path in app.openapi()["paths"]:
        assert not (path.startswith("/api/agent/") and path.endswith("/letter"))
