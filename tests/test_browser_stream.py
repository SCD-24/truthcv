"""The noVNC WebSocket relay refuses cross-origin connections.

WebSockets bypass the same-origin policy and CORS does not apply to them, so
this check is the only thing standing between a page the operator happens to
visit and keyboard control of a browser logged into their accounts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import api.browser_stream as browser_stream
from api.browser_stream import origin_allowed, peer_allowed
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

    def test_a_trailing_dot_loopback_hostname_is_allowed(self):
        assert origin_allowed("http://localhost.:5627", "localhost.:5627") is True

    def test_expanded_ipv6_loopback_is_allowed(self):
        assert origin_allowed("http://[::ffff:127.0.0.1]:5627", "[::ffff:127.0.0.1]:5627") is True

    def test_a_malformed_authority_with_a_dotted_port_is_refused(self):
        """urlparse splits the authority at the first colon, so a malformed
        port like "5627.evil.example" would otherwise leave hostname
        "localhost" (allowlisted) with the bogus port never examined."""
        assert (
            origin_allowed(
                "http://localhost:5627.evil.example", "localhost:5627.evil.example"
            )
            is False
        )


class TestPeerAllowed:
    """The one signal Origin/Host cannot forge: the actual TCP peer address."""

    def test_loopback_ipv4_is_allowed(self):
        assert peer_allowed("127.0.0.1") is True

    def test_loopback_ipv6_is_allowed(self):
        assert peer_allowed("::1") is True

    def test_mapped_loopback_ipv6_is_allowed(self):
        assert peer_allowed("::ffff:127.0.0.1") is True

    def test_a_non_loopback_peer_is_refused(self):
        assert peer_allowed("10.0.0.5") is False

    def test_a_container_hostname_peer_is_refused(self):
        assert peer_allowed("agent") is False

    def test_an_empty_peer_is_refused(self):
        assert peer_allowed("") is False

    def test_the_resolved_gateway_is_allowed_inside_a_container(self, monkeypatch):
        """Docker NATs a published port, so the operator's own browser arrives
        with the bridge gateway as its source, never 127.0.0.1."""
        monkeypatch.setattr(browser_stream, "_DEFAULT_GATEWAY", "172.18.0.1")
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: True)
        assert peer_allowed("172.18.0.1") is True

    def test_the_gateway_is_refused_outside_a_container(self, monkeypatch):
        """Off a container, the same lookup just names the LAN router: a peer
        that happens to be it must not be silently trusted."""
        monkeypatch.setattr(browser_stream, "_DEFAULT_GATEWAY", "192.168.178.1")
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: False)
        assert peer_allowed("192.168.178.1") is False

    def test_a_sibling_container_that_is_not_the_gateway_is_refused(self, monkeypatch):
        """A container on the same compose network (e.g. `agent`) keeps its own
        address; only the gateway means "arrived from the host". Refused both
        inside and outside a container."""
        monkeypatch.setattr(browser_stream, "_DEFAULT_GATEWAY", "172.18.0.1")
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: True)
        assert peer_allowed("172.18.0.4") is False
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: False)
        assert peer_allowed("172.18.0.4") is False

    def test_loopback_is_allowed_regardless_of_container_status(self, monkeypatch):
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: True)
        assert peer_allowed("127.0.0.1") is True
        monkeypatch.setattr(browser_stream, "_running_in_container", lambda: False)
        assert peer_allowed("127.0.0.1") is True

    def test_an_extra_allowed_peer_can_be_configured(self, monkeypatch):
        monkeypatch.setenv("BROWSER_STREAM_ALLOWED_PEERS", "172.20.0.9")
        assert peer_allowed("172.20.0.9") is True

    def test_widening_the_peer_allowlist_is_logged(self, monkeypatch, caplog):
        """The peer allowlist is the strongest gate in this module; widening it
        must be at least as visible as widening the (weaker) Origin allowlist."""
        monkeypatch.setattr(browser_stream, "_logged_extra_peers", False)
        monkeypatch.setenv("BROWSER_STREAM_ALLOWED_PEERS", "172.20.0.9")
        with caplog.at_level("WARNING", logger="api.browser_stream"):
            peer_allowed("172.20.0.9")
        assert any(
            "BROWSER_STREAM_ALLOWED_PEERS" in record.getMessage() for record in caplog.records
        )


class TestRunningInContainer:
    def test_the_marker_file_present_means_in_a_container(self, tmp_path):
        marker = tmp_path / ".dockerenv"
        marker.write_text("")
        assert browser_stream._running_in_container(str(marker)) is True

    def test_no_marker_file_means_not_in_a_container(self, tmp_path):
        assert browser_stream._running_in_container(str(tmp_path / "no-such-file")) is False


class TestDefaultGateway:
    """Pinned against a fixture route table, not just the live machine's route,
    so the little-endian byte order handling can't silently regress."""

    def test_parses_a_fixture_route_table(self, tmp_path):
        route_table = (
            "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
            "eth0\t00000000\t0100000A\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"
            "eth0\t0000000A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
        )
        fixture = tmp_path / "route"
        fixture.write_text(route_table)
        # 0100000A little-endian -> bytes 0A 00 00 01 -> 10.0.0.1
        assert browser_stream._default_gateway(str(fixture)) == "10.0.0.1"

    def test_a_missing_route_file_resolves_to_empty(self, tmp_path):
        assert browser_stream._default_gateway(str(tmp_path / "does-not-exist")) == ""

    def test_no_default_route_resolves_to_empty(self, tmp_path):
        route_table = (
            "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
            "eth0\t0000000A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"
        )
        fixture = tmp_path / "route"
        fixture.write_text(route_table)
        assert browser_stream._default_gateway(str(fixture)) == ""


class TestRelayHandshake:
    def test_cross_origin_connection_is_rejected(self, client):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/browser/session/stream",
                headers={"Origin": "http://evil.example"},
            ):
                pass

    def test_non_loopback_peer_is_rejected_even_with_a_matching_origin(self, client):
        """TestClient's synthetic peer ("testclient", not loopback) must be refused
        even when Origin and Host are set to agree on a loopback identity — proving
        the peer check, not just the origin check, is doing work here."""
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/browser/session/stream",
                headers={"Origin": "http://localhost:5627", "Host": "localhost:5627"},
            ):
                pass
        assert exc_info.value.code == 1008

    def test_upstream_handshake_failure_closes_cleanly(self, client, monkeypatch):
        """A malformed upstream handshake (websockets.WebSocketException, not
        OSError) must not propagate out of the ASGI app as an unhandled error."""

        def _peer_allowed(_peer: str) -> bool:
            return True

        class _FailingConnect:
            """Stands in for `websockets.connect(...)`'s async context manager,
            failing on __aenter__ the way a bad handshake (wrong service on the
            port, no "binary" subprotocol offered, ...) would."""

            async def __aenter__(self):
                raise browser_stream.websockets.InvalidURI("ws://bad", "not a valid uri")

            async def __aexit__(self, *_exc_info):
                return False

        def _connect(*_args, **_kwargs):
            return _FailingConnect()

        monkeypatch.setattr(browser_stream, "peer_allowed", _peer_allowed)
        monkeypatch.setattr(browser_stream.websockets, "connect", _connect)

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/api/browser/session/stream",
                headers={"Origin": "http://localhost:5627", "Host": "localhost:5627"},
            ) as ws:
                # The accept happens before the upstream connect fails, so the
                # close arrives as a message rather than at entry; read it.
                ws.receive_bytes()
        assert exc_info.value.code == 1011
