"""Unit tests for services.agent_credentials: error branches and null stages."""

import pytest

import modelrouting
import services.agent_credentials as svc
from api.schemas import AgentLlmCredentials
from connections.auth.claude import AuthError
from modelrouting import Route, Routing
from services.errors import NotFound, Unavailable

_SHA = "a" * 64


def _conns(monkeypatch, conns: dict) -> None:
    monkeypatch.setattr(svc.secretstore, "get_connection", lambda card: conns.get(card, {}))


def _raise_auth(**_kw):
    raise AuthError("expired")


def test_unknown_card_and_missing_key_are_not_found(monkeypatch):
    _conns(monkeypatch, {})
    for route in (Route("nope", "m"), Route("claude", "m"), Route("codex", "m"),
                  Route("openrouter", "m"), Route("ollama", "m")):
        with pytest.raises(NotFound, match="^Not Found$"):
            svc.credentials_for_route(route)


def test_claude_oauth_auth_error_is_unavailable(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}}})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_auth)
    with pytest.raises(Unavailable, match="^Claude subscription needs reconnecting.$"):
        svc.credentials_for_route(None)


def test_credentials_dict_matches_wire_model_dump(monkeypatch):
    _conns(monkeypatch, {"ollama": {"baseUrl": "http://o"}})
    got = svc.credentials_for_route(Route("ollama", "small"))
    assert got == AgentLlmCredentials.model_validate(got).model_dump(by_alias=True)
    assert list(got) == ["authType", "token", "model", "baseUrl", "provider", "wire"]


def test_refresh_without_oauth_is_not_found(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}, "authMode": "apikey"}})
    with pytest.raises(NotFound, match="^Not Found$"):
        svc.refresh_token("claude", _SHA)


def test_refresh_auth_error_is_unavailable(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}}})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_auth)
    with pytest.raises(Unavailable, match="^Claude subscription needs reconnecting.$"):
        svc.refresh_token("claude", _SHA)


def test_refresh_passes_rejected_sha(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}}})
    monkeypatch.setattr(svc, "get_valid_access_token", lambda **kw: "new-" + kw["rejected_sha256"])
    assert svc.refresh_token("claude", _SHA) == "new-" + _SHA


def test_stage_routes_nulls_failing_and_unrouted_stages(monkeypatch):
    _conns(monkeypatch, {})
    monkeypatch.setitem(
        svc._CARD_CREDENTIALS, "ollama", lambda model: {"model": model, "provider": "ollama"}
    )
    modelrouting.save(Routing(
        agent=Route("claude", "m"),
        agent_stages={"screening": Route("ollama", "small")},
    ))
    assert svc.stage_routes() == {"stages": {
        "apply": None,
        "screening": {"model": "small", "provider": "ollama"},
        "extract": None,
    }}
