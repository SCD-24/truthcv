"""The noVNC WebSocket relay refuses cross-origin connections.

WebSockets bypass the same-origin policy and CORS does not apply to them, so
this check is the only thing standing between a page the operator happens to
visit and keyboard control of a browser logged into their accounts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.browser_stream import origin_allowed
from api.main import app


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


class TestOriginAllowed:
    def test_same_origin_is_allowed(self):
        assert origin_allowed("http://localhost:5627", "localhost:5627") is True

    def test_https_same_host_is_allowed(self):
        assert origin_allowed("https://localhost:5627", "localhost:5627") is True

    def test_a_different_host_is_refused(self):
        assert origin_allowed("http://evil.example", "localhost:5627") is False

    def test_a_different_port_on_the_same_host_is_refused(self):
        assert origin_allowed("http://localhost:9999", "localhost:5627") is False

    def test_a_missing_origin_is_refused(self):
        """A browser always sends Origin on a WebSocket handshake. Absence is not a browser."""
        assert origin_allowed("", "localhost:5627") is False

    def test_a_host_prefix_attack_is_refused(self):
        assert origin_allowed("http://localhost:5627.evil.example", "localhost:5627") is False

    def test_a_garbage_origin_is_refused(self):
        assert origin_allowed("not a url", "localhost:5627") is False

    def test_dns_rebinding_origin_is_refused(self):
        """Origin and Host agreeing is not enough: under DNS rebinding an attacker
        controls both. Only loopback hostnames may reach this socket."""
        assert origin_allowed("http://evil.example:5627", "evil.example:5627") is False

    def test_loopback_ip_origin_is_allowed(self):
        assert origin_allowed("http://127.0.0.1:5627", "127.0.0.1:5627") is True

    def test_an_extra_allowed_host_can_be_configured(self, monkeypatch):
        monkeypatch.setenv("BROWSER_STREAM_ALLOWED_HOSTS", "truthcv.local")
        assert origin_allowed("http://truthcv.local:5627", "truthcv.local:5627") is True

    def test_a_configured_host_still_requires_the_ports_to_match(self, monkeypatch):
        monkeypatch.setenv("BROWSER_STREAM_ALLOWED_HOSTS", "truthcv.local")
        assert origin_allowed("http://truthcv.local:9999", "truthcv.local:5627") is False


class TestRelayHandshake:
    def test_cross_origin_connection_is_rejected(self, client):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/browser/session/stream",
                headers={"Origin": "http://evil.example"},
            ):
                pass
