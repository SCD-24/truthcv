"""API surface for operator-editable prompt fragments and presets.

Seeded records are code-defined and read-only over HTTP; user records layer on
top in JSON. Slots are a display grouping only — nothing here enforces
exclusivity within a slot, and the validate-a-preset route (which used to
enforce it) has been removed entirely.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app
from prompts.fragments import SEEDED_FRAGMENTS, SEEDED_PRESETS
from storage.paths import data_dir


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def test_get_prompt_fragments_includes_all_seeded_ids(client):
    """Every seeded fragment id ships in the list, unconditionally."""
    r = client.get("/api/prompt-fragments")
    assert r.status_code == 200
    ids = {f["id"] for f in r.json()}
    assert {f.id for f in SEEDED_FRAGMENTS} <= ids


def test_create_fragment_with_blank_id_slugifies_the_title(client):
    """A blank id is derived from the title, not rejected."""
    r = client.post(
        "/api/prompt-fragments",
        json={"id": "", "slot": "voice", "title": "My New Voice!", "text": "Some text."},
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == "my-new-voice"


def test_put_seeded_fragment_is_403(client):
    """Seeded fragments can never be edited, even with a valid body."""
    seeded_id = SEEDED_FRAGMENTS[0].id
    r = client.put(
        f"/api/prompt-fragments/{seeded_id}",
        json={"id": seeded_id, "slot": "voice", "title": "Hacked", "text": "Hacked."},
    )
    assert r.status_code == 403


def test_delete_seeded_fragment_is_403(client):
    """Seeded fragments can never be deleted."""
    seeded_id = SEEDED_FRAGMENTS[0].id
    r = client.delete(f"/api/prompt-fragments/{seeded_id}")
    assert r.status_code == 403


def test_delete_fragment_referenced_by_preset_is_400(client):
    """A fragment still selected by some preset cannot be deleted out from under it."""
    client.post(
        "/api/prompt-fragments",
        json={"id": "", "slot": "voice", "title": "Referenced Voice", "text": "Some text."},
    )
    client.post(
        "/api/prompt-presets",
        json={
            "id": "uses-referenced-voice",
            "name": "Uses Referenced Voice",
            "fragmentIds": ["referenced-voice", "structure-classic"],
            "isDefault": False,
        },
    )
    r = client.delete("/api/prompt-fragments/referenced-voice")
    assert r.status_code == 400


def test_preset_with_two_fragments_in_same_slot_is_accepted(client):
    """Slot exclusivity is gone: a preset may hold two voice fragments at once,
    and both survive, in order, in the response."""
    r = client.post(
        "/api/prompt-presets",
        json={
            "id": "double-voice",
            "name": "Double Voice",
            "fragmentIds": ["voice-professional", "voice-warm", "structure-classic"],
            "isDefault": False,
        },
    )
    assert r.status_code == 200, r.text
    fragment_ids = r.json()["fragmentIds"]
    assert fragment_ids.index("voice-professional") < fragment_ids.index("voice-warm")
    assert "voice-professional" in fragment_ids and "voice-warm" in fragment_ids


def test_set_default_on_seeded_preset_writes_no_seeded_record(client):
    """Marking a seeded preset default only writes the standalone marker file;
    it never persists a copy of the seeded preset into prompt_presets.json."""
    seeded_id = SEEDED_PRESETS[0].id
    r = client.put(f"/api/prompt-presets/{seeded_id}/default")
    assert r.status_code == 200, r.text
    assert r.json()["isDefault"] is True

    presets_path = data_dir() / "prompt_presets.json"
    seeded_ids = {p.id for p in SEEDED_PRESETS}
    if presets_path.exists():
        records = json.loads(presets_path.read_text(encoding="utf-8"))
        assert all(record.get("id") not in seeded_ids for record in records)


def test_validate_route_is_gone(client):
    """POST /api/prompt-presets/validate was deleted along with conflict machinery.

    "validate" now only matches the /api/prompt-presets/{id} path, which has no
    POST handler, so the API answers 405 rather than 404 — either way the
    validation endpoint is gone and no conflict report comes back.
    """
    r = client.post("/api/prompt-presets/validate", json={"fragmentIds": []})
    assert r.status_code in (404, 405)
    assert "conflicts" not in r.text
