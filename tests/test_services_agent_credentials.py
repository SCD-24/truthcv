"""Unit tests for truthcv.services.agent_credentials: error branches and null stages."""

import pytest

import truthcv.integrations.modelrouting as modelrouting
import truthcv.services.agent_credentials as svc
from truthcv.adapters.http.schemas import AgentLlmCredentials
from truthcv.integrations.connections.auth.claude import AuthError
from truthcv.integrations.modelrouting import Route, Routing
from truthcv.services.errors import NotFound, Unavailable

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


def _raise_reconnect(**_kw):
    raise AuthError("dead", reconnect_required=True)


def _raise_codex_reconnect(**_kw):
    raise svc.codex_auth.AuthError("dead", reconnect_required=True)


def test_dead_claude_subscription_falls_back_to_api_key(monkeypatch, caplog):
    _conns(monkeypatch, {"claude": {
        "oauth": {"accessToken": "t", "reauthRequired": True}, "apiKey": "sk-ant-fallback",
    }})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_reconnect)
    with caplog.at_level("WARNING", logger=svc.__name__):
        got = svc.credentials_for_route(Route("claude", "m"))
    assert got == {
        "authType": "api_key", "token": "sk-ant-fallback", "model": "m",
        "baseUrl": "", "provider": "claude", "wire": "anthropic-messages",
    }
    assert "falling back" in caplog.text
    assert "sk-ant-fallback" not in caplog.text and "'t'" not in caplog.text


def test_refresh_reconnect_error_falls_back_to_api_key(monkeypatch):
    # Not yet marked: the refresh itself is what discovers the dead grant.
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}, "apiKey": "sk-ant-fb"}})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_reconnect)
    assert svc.credentials_for_route(None)["token"] == "sk-ant-fb"


def test_dead_codex_subscription_falls_back_to_api_key(monkeypatch):
    _conns(monkeypatch, {"codex": {"oauth": {"accessToken": "t"}, "apiKey": "sk-codex-fb"}})
    monkeypatch.setattr(svc.codex_auth, "get_valid_access_token", _raise_codex_reconnect)
    got = svc.credentials_for_route(Route("codex", "gpt-5"))
    assert (got["authType"], got["token"], got["wire"]) == (
        "api_key", "sk-codex-fb", "openai-chat-completions")


def test_dead_subscription_without_api_key_is_unavailable(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t", "reauthRequired": True}}})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_reconnect)
    with pytest.raises(Unavailable, match="^Claude subscription needs reconnecting.$"):
        svc.credentials_for_route(None)


def test_transient_refresh_error_does_not_fall_back(monkeypatch):
    _conns(monkeypatch, {"claude": {"oauth": {"accessToken": "t"}, "apiKey": "sk-ant-fb"}})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_auth)
    with pytest.raises(Unavailable):
        svc.credentials_for_route(None)


def test_dead_subscription_stage_routes_use_api_key(monkeypatch):
    _conns(monkeypatch, {"claude": {
        "oauth": {"accessToken": "t", "reauthRequired": True}, "apiKey": "sk-ant-fb",
    }})
    monkeypatch.setattr(svc, "get_valid_access_token", _raise_reconnect)
    modelrouting.save(Routing(agent=Route("claude", "m")))
    assert svc.stage_routes()["stages"]["apply"]["authType"] == "api_key"


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
