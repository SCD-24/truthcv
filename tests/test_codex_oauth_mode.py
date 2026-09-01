"""Tests for the codex OAuth subscription path in the provider layer."""

import time
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

from connections.auth import codex as codex_auth
from providers.openai_provider import OpenAIProvider
from providers import build_connection_provider
from cryptography.fernet import Fernet


@pytest.fixture()
def enc(data_dir, monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    return data_dir


# ---------------------------------------------------------------------------
# complete_via_responses — happy path
# ---------------------------------------------------------------------------

@respx.mock
def test_complete_via_responses_builds_correct_url_headers_and_body(monkeypatch):
    """URL, headers, and body are correct; store:false, stream:true, no max_output_tokens."""
    from providers import codex_responses as cr

    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(200, text='data: {"type":"response.completed","response":{"completed_reason":"stop"}}\ndata: [DONE]\n')
    )
    token = "tok-at"
    account = "acct-1"
    model = "gpt-5.4"
    out = cr.complete_via_responses(token, account, model, "sys", [], effort=None)
    # Read back the captured request
    req = route.calls.last.request
    assert req.url == cr.DEFAULT_BASE_URL + "/responses"
    assert req.headers["authorization"] == f"Bearer {token}"
    assert req.headers["chatgpt-account-id"] == account
    assert req.headers["openai-beta"] == "responses=experimental"
    assert req.headers["accept"] == "text/event-stream"
    body = req.read().decode()
    parsed = {"store": False, "stream": True}  # quick check
    import json as _json

    j = _json.loads(body)
    assert j["store"] is False
    assert j["stream"] is True
    assert "max_output_tokens" not in j


@respx.mock
def test_complete_via_responses_accumulates_deltas_and_stops_at_completed():
    """Multiple output_text.delta events are assembled; response.completed ends the stream."""
    from providers import codex_responses as cr

    events = [
        'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":"Hello"}}}\n',
        'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":" world"}}}\n',
        'data: {"type":"response.completed","response":{"completed_reason":"stop"}}\n',
    ]
    text = "\n".join(events)
    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(200, text=text)
    )
    out = cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
    assert out == "Hello world"


@respx.mock
def test_complete_via_responses_error_event_raises_provider_error():
    """An SSE error event raises ProviderError with the server's code and message."""
    from providers import codex_responses as cr
    from providers.base import ProviderError

    events = [
        'data: {"type":"error","error":{"code":"some_code","message":"something bad"}}\n',
        'data: {"type":"response.completed","response":{"completed_reason":"stop"}}\n',
    ]
    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(200, text="\n".join(events))
    )
    try:
        cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
        assert False, "Expected ProviderError"
    except ProviderError as e:
        assert "some_code" in str(e)
        assert "something bad" in str(e)


@respx.mock
def test_complete_via_responses_response_failed_raises():
    """An SSE response.failed event raises ProviderError."""
    from providers import codex_responses as cr
    from providers.base import ProviderError

    events = [
        'data: {"type":"response.failed","response":{"error":{"code":"internal_error","message":"server fault"}}}\n',
    ]
    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(200, text="\n".join(events))
    )
    try:
        cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
        assert False, "Expected ProviderError"
    except ProviderError as e:
        assert "internal_error" in str(e)


@respx.mock
def test_complete_via_responses_non_2xx_raises():
    """A non-2xx HTTP status raises ProviderError with the status code."""
    from providers import codex_responses as cr
    from providers.base import ProviderError

    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(500, json={"error": {"code": "server_error", "message": "boom"}})
    )
    try:
        cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
        assert False, "Expected ProviderError"
    except ProviderError as e:
        # The error message includes the error code from the body
        assert "server_error" in str(e)
        assert "boom" in str(e)


@respx.mock
def test_complete_via_responses_429_usage_limit_raises_with_resets_at():
    """HTTP 429 with usage_limit_reached raises a terminal ProviderError with resets_at."""
    from providers import codex_responses as cr
    from providers.base import ProviderError

    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(429, json={
            "error": {"code": "usage_limit_reached", "message": "Limit reached.", "resets_at": 1234567890}
        })
    )
    try:
        cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
        assert False, "Expected ProviderError"
    except ProviderError as e:
        assert "usage limit" in str(e).lower()
        assert "1234567890" in str(e)


@respx.mock
def test_complete_via_responses_incomplete_stream_raises():
    """A stream ending without response.completed raises ProviderError, not partial text."""
    from providers import codex_responses as cr
    from providers.base import ProviderError

    events = [
        'data: {"type":"response.output_text.delta","response":{"output_text":{"delta":"partial"}}}\n',
    ]
    route = respx.post(cr.DEFAULT_BASE_URL + "/responses").mock(
        return_value=Response(200, text="\n".join(events))
    )
    try:
        cr.complete_via_responses("tok", "acct", "gpt-5.4", "sys", [])
        assert False, "Expected ProviderError"
    except ProviderError as e:
        assert "completion" in str(e).lower()


# ---------------------------------------------------------------------------
# OpenAIProvider OAuth path
# ---------------------------------------------------------------------------

def test_oauth_provider_key_is_codex_even_with_base_url(monkeypatch):
    """_provider_key is pinned to 'codex' when oauth_token is set, even if base_url is passed."""
    with patch.object(codex_auth, "account_id", return_value="acct-oauth"):
        provider = OpenAIProvider(model="gpt-5.4", oauth_token="tok-oauth", base_url="http://custom")
    assert provider._provider_key == "codex"


def test_oauth_provider_constructs_without_openai_api_key(monkeypatch):
    """OpenAIProvider(oauth_token=...) succeeds when OPENAI_API_KEY is not set."""
    import os

    api_key_backup = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with patch.object(codex_auth, "account_id", return_value="acct-oauth"):
            provider = OpenAIProvider(model="gpt-5.4", oauth_token="tok-oauth")
        assert provider._oauth_token == "tok-oauth"
        assert provider._provider_key == "codex"
    finally:
        if api_key_backup is not None:
            os.environ["OPENAI_API_KEY"] = api_key_backup


def test_oauth_list_models_returns_static_allowlist():
    """list_models() in oauth mode returns the static CODEX_SUBSCRIPTION_MODELS allow-list."""
    from providers.codex_responses import CODEX_SUBSCRIPTION_MODELS

    with patch.object(codex_auth, "account_id", return_value="acct-oauth"):
        provider = OpenAIProvider(model="gpt-5.4", oauth_token="tok-oauth")
    models = provider.list_models()
    ids = [m["id"] for m in models]
    assert ids == list(CODEX_SUBSCRIPTION_MODELS)


# ---------------------------------------------------------------------------
# build_connection_provider OAuth branch
# ---------------------------------------------------------------------------

def test_build_connection_provider_selects_oauth_branch_for_subscription_codex(data_dir, monkeypatch, enc):
    """When authMode != 'apikey' and oauth record is present, the oauth branch is selected."""
    from connections.auth.claude import AuthError
    import secretstore

    secretstore.set_connection("codex", {
        "oauth": {
            "accessToken": "tok-oauth-codex",
            "refreshToken": "rt-oauth-codex",
            "expiresAt": time.time() + 3600,
            "scope": "",
            "connectedAt": time.time(),
        },
        "authMode": "subscription",
    })
    with patch.object(codex_auth, "get_valid_access_token", return_value="tok-oauth-codex"):
        with patch.object(codex_auth, "account_id", return_value="acct-codex"):
            provider = build_connection_provider("codex", "gpt-5.4")
    assert provider._provider_key == "codex"
    assert provider._oauth_token == "tok-oauth-codex"


def test_build_connection_provider_selects_apikey_branch_when_authmode_is_apikey(data_dir, monkeypatch, enc):
    """Even when an oauth record is present, authMode='apikey' forces the api-key path."""
    import secretstore

    secretstore.set_connection("codex", {
        "oauth": {"accessToken": "tok-stale", "refreshToken": "rt", "expiresAt": time.time() + 3600, "scope": "", "connectedAt": 0},
        "authMode": "apikey",
        "apiKey": "sk-test-apikey",
    })
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-apikey")
    provider = build_connection_provider("codex", "gpt-4o")
    assert provider._provider_key == "codex"
    assert provider._oauth_token is None


# ---------------------------------------------------------------------------
# Cache key includes auth mode
# ---------------------------------------------------------------------------

def test_cache_returns_different_instance_after_auth_mode_changes(data_dir, monkeypatch, enc):
    """Switching the codex card's auth mode clears the cache for that card."""
    import secretstore
    from providers import _cache, reset_provider

    reset_provider()

    # First: api-key mode
    secretstore.set_connection("codex", {"authMode": "apikey", "apiKey": "sk-apikey-cache"})
    monkeypatch.setenv("OPENAI_API_KEY", "sk-apikey-cache")
    p1 = build_connection_provider("codex", "gpt-4o")
    assert p1._oauth_token is None

    # Switch to subscription mode
    secretstore.set_connection("codex", {
        "oauth": {"accessToken": "tok-sub-cache", "refreshToken": "rt", "expiresAt": time.time() + 3600, "scope": "", "connectedAt": time.time()},
        "authMode": "subscription",
    })
    with patch.object(codex_auth, "get_valid_access_token", return_value="tok-sub-cache"):
        with patch.object(codex_auth, "account_id", return_value="acct-cache"):
            p2 = build_connection_provider("codex", "gpt-5.4")
    assert p2._oauth_token == "tok-sub-cache"
    # p1 and p2 must be different instances — cache key includes auth mode
    assert p1 is not p2
