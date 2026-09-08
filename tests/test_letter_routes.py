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
            "company": "Contoso Labs",
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
    import agenttools.letter_operator as letter_operator

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _StubProvider())
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
    import agenttools.letter_operator as letter_operator

    class _Overclaiming:
        def extract_json(self, system, messages, schema=None):
            return {
                "paragraphs": [
                    {
                        "text": "I personally invented Kubernetes at Contoso Labs.",
                        "claims": ["invented Kubernetes"],
                    }
                ]
            }

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _Overclaiming())
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
    cfg.blocked_companies = ["Contoso Labs"]
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


def test_blocked_generation_exposes_claim_ids_and_paragraphs(client, monkeypatch):
    """The 422 detail must carry everything the UI needs to offer approve/deny:
    a stable claimId per blocked claim, its experienceId, text and tokens, and
    the paragraphs actually generated (so a retry can re-validate them without
    a second LLM call)."""
    import agenttools.letter_operator as letter_operator

    class _Overclaiming:
        def extract_json(self, system, messages, schema=None):
            return {
                "paragraphs": [
                    {
                        "text": "I personally invented Kubernetes at Contoso Labs.",
                        "claims": ["invented Kubernetes"],
                    }
                ]
            }

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _Overclaiming())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["message"] == "The letter was blocked by the truthfulness guardrail."
    claims = detail["blockedClaims"]
    assert len(claims) == 1
    claim = claims[0]
    assert claim["claimId"]
    assert claim["experienceId"] == "letter"
    assert claim["text"] == "invented Kubernetes"
    assert claim["tokens"]
    assert detail["paragraphs"] == [
        {"text": "I personally invented Kubernetes at Contoso Labs.", "claims": ["invented Kubernetes"]}
    ]
    assert letters.load(s.id) is None


def _blocked_response(client, monkeypatch, call_counter):
    import agenttools.letter_operator as letter_operator

    class _Overclaiming:
        def extract_json(self, system, messages, schema=None):
            call_counter["n"] += 1
            return {
                "paragraphs": [
                    {
                        "text": "I personally invented Kubernetes at Contoso Labs.",
                        "claims": ["invented Kubernetes"],
                    }
                ]
            }

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _Overclaiming())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    return s, r.json()["detail"]


def test_approving_the_blocked_claim_saves_and_does_not_call_the_provider_again(client, monkeypatch):
    call_counter = {"n": 0}
    s, detail = _blocked_response(client, monkeypatch, call_counter)
    assert call_counter["n"] == 1
    claim_id = detail["blockedClaims"][0]["claimId"]

    r = client.post(
        f"/api/screenings/{s.id}/letter",
        json={
            "approvals": {"approvedClaimIds": [claim_id], "deniedClaimIds": []},
            "paragraphs": detail["paragraphs"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "generated"
    assert call_counter["n"] == 1  # no second LLM call: the given paragraphs were reused
    assert letters.load(s.id) is not None
    assert letters.load(s.id).source == "generated"


def test_approving_the_blocked_claim_writes_nothing_to_truth(client, monkeypatch):
    from truth import load as load_truth

    call_counter = {"n": 0}
    s, detail = _blocked_response(client, monkeypatch, call_counter)
    claim_id = detail["blockedClaims"][0]["claimId"]
    before = load_truth()

    r = client.post(
        f"/api/screenings/{s.id}/letter",
        json={
            "approvals": {"approvedClaimIds": [claim_id], "deniedClaimIds": []},
            "paragraphs": detail["paragraphs"],
        },
    )
    assert r.status_code == 200, r.text
    after = load_truth()
    assert before == after


def test_denying_the_blocked_claim_drops_it(client, monkeypatch):
    call_counter = {"n": 0}
    s, detail = _blocked_response(client, monkeypatch, call_counter)
    claim_id = detail["blockedClaims"][0]["claimId"]

    r = client.post(
        f"/api/screenings/{s.id}/letter",
        json={
            "approvals": {"approvedClaimIds": [], "deniedClaimIds": [claim_id]},
            "paragraphs": detail["paragraphs"],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["source"] == "generated"


def test_generate_without_preset_id_uses_default_preset_prompt(client, monkeypatch):
    """Omitting presetId must resolve through prompts.library.default_preset(),
    not silently fall back to some other preset (or error) — the system
    prompt the provider actually receives must match what that default
    preset produces."""
    import agenttools.letter_operator as letter_operator
    from prompts import cover_letter_system_for_preset
    from prompts.library import default_preset

    captured: dict = {}

    class _CapturingProvider:
        def extract_json(self, system, messages, schema=None):
            captured["system"] = system
            return {"paragraphs": [{"text": "It is the work that was created.", "claims": []}]}

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _CapturingProvider())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 200, r.text
    assert captured["system"] == cover_letter_system_for_preset(default_preset().id, "Standard")


def test_generate_with_explicit_preset_id_uses_that_presets_prompt(client, monkeypatch):
    """A presetId in the request body selects that preset's prompt — one that
    is distinctly not the default preset's — proving the given id actually
    reaches prompt assembly rather than being ignored."""
    import agenttools.letter_operator as letter_operator
    from prompts import cover_letter_system_for_preset
    from prompts.library import default_preset

    captured: dict = {}

    class _CapturingProvider:
        def extract_json(self, system, messages, schema=None):
            captured["system"] = system
            return {"paragraphs": [{"text": "It is the work that was created.", "claims": []}]}

    monkeypatch.setattr(letter_operator, "get_provider", lambda _name: _CapturingProvider())
    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={"presetId": "concise"})
    assert r.status_code == 200, r.text
    expected = cover_letter_system_for_preset("concise", "Standard")
    assert captured["system"] == expected
    assert captured["system"] != cover_letter_system_for_preset(default_preset().id, "Standard")


def test_unknown_preset_id_errors_instead_of_silently_falling_back(client, monkeypatch):
    """An unknown presetId must surface to the caller as an error, never a
    silent fallback to the default preset's letter: no 200 is acceptable
    here, whatever the exact status code turns out to be."""
    import api.routes as routes
    from providers.fake import FakeProvider
    from truth import save
    from truth.model import Experience, Skill, Truth

    def router(system, messages, schema):
        return {
            "paragraphs": [
                {"text": "I use Python at Acme Corp.", "claims": ["Python", "Acme Corp"]}
            ]
        }

    monkeypatch.setattr(routes, "get_provider", lambda *a, **k: FakeProvider(router=router))
    save(
        Truth(
            experiences=[
                Experience(
                    id="c1",
                    role="Engineer",
                    company="Acme Corp",
                    start="2020",
                    end="2023",
                    source="linkedin-pdf",
                )
            ],
            education=[],
            skills=[Skill(id="s1", value="Python", source="linkedin-pdf")],
        )
    )
    from storage import data_dir as dd

    (dd() / "posting.txt").write_text("Python role at a startup")

    r = client.post(
        "/api/cover-letter", json={"length": "Short", "presetId": "no-such-preset"}
    )
    assert r.status_code >= 400
    assert r.status_code != 200


def test_company_blocked_letter_has_no_claims_and_blocked_reason(client):
    """The blocklist refusal keeps its distinct shape: no claims, a named reason."""
    import agentconfig.store as agent_config_store

    cfg = agent_config_store.load()
    cfg.blocked_companies = ["Contoso Labs"]
    agent_config_store.save(cfg)

    s = _queued()
    r = client.post(f"/api/screenings/{s.id}/letter", json={})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["blockedReason"] == "company_blocked"
    assert detail["blockedClaims"] == []
    assert letters.load(s.id) is None
