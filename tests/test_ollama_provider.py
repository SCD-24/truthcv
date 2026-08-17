"""OllamaProvider: bearer token wiring onto its HTTP calls."""

from __future__ import annotations

import respx
from httpx import Response

from providers.ollama_provider import OllamaProvider


@respx.mock
def test_list_models_sends_bearer_header_when_set():
    route = respx.get("http://localhost:11434/api/tags").mock(
        return_value=Response(200, json={"models": []})
    )
    OllamaProvider(host="http://localhost:11434", bearer="tok-123").list_models()
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok-123"


@respx.mock
def test_list_models_omits_header_when_no_bearer():
    route = respx.get("http://localhost:11434/api/tags").mock(
        return_value=Response(200, json={"models": []})
    )
    OllamaProvider(host="http://localhost:11434").list_models()
    assert "Authorization" not in route.calls[0].request.headers


@respx.mock
def test_chat_sends_bearer_header_when_set():
    route = respx.post("http://localhost:11434/api/chat").mock(
        return_value=Response(200, json={"message": {"content": "hi"}})
    )
    provider = OllamaProvider(host="http://localhost:11434", bearer="tok-456")
    provider.complete("system", [{"role": "user", "content": "hello"}])
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok-456"
