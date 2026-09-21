from unittest.mock import MagicMock, patch

from connections.auth.claude import CLAUDE_CODE_PREAMBLE
from providers.anthropic_provider import AnthropicProvider


def _fake_anthropic(captured: dict):
    fake_sdk = MagicMock()

    def ctor(**kwargs):
        captured["ctor"] = kwargs
        client = MagicMock()
        block = MagicMock(type="text", text="pong")
        client.messages.create.side_effect = lambda **kw: (captured.update(create=kw), MagicMock(content=[block]))[1]
        return client

    fake_sdk.Anthropic.side_effect = ctor
    return fake_sdk


def test_oauth_mode_uses_bearer_beta_and_preamble(monkeypatch):
    captured: dict = {}
    with patch("connections.auth.claude.get_valid_access_token", return_value="tok-1"):
        provider = AnthropicProvider(model="claude-opus-4-8", oauth=True)
        provider._anthropic = _fake_anthropic(captured)
        assert provider.complete("do a thing", [{"role": "user", "content": "hi"}]) == "pong"
    assert captured["ctor"]["auth_token"] == "tok-1"
    assert captured["ctor"]["default_headers"] == {"anthropic-beta": "oauth-2025-04-20"}
    system = captured["create"]["system"]
    assert len(system) == 2
    assert system[0] == {"type": "text", "text": CLAUDE_CODE_PREAMBLE}
    assert "cache_control" not in system[0]
    assert system[1] == {
        "type": "text",
        "text": "do a thing",
        "cache_control": {"type": "ephemeral"},
    }


def test_key_mode_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    provider = AnthropicProvider()
    assert provider._oauth is False


def test_key_mode_system_has_cache_control(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-x")
    captured: dict = {}
    provider = AnthropicProvider()
    provider._anthropic = _fake_anthropic(captured)
    provider._client = provider._anthropic.Anthropic()
    assert provider.complete("do a thing", [{"role": "user", "content": "hi"}]) == "pong"
    system = captured["create"]["system"]
    assert len(system) == 1
    assert system[0] == {
        "type": "text",
        "text": "do a thing",
        "cache_control": {"type": "ephemeral"},
    }
