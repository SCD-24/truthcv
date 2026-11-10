"""Wire models for provider connections and login flows."""

from __future__ import annotations

from .common import _Camel


class ConnectionStatus(_Camel):
    """One catalog card's connection state — never carries token material."""

    provider: str
    label: str
    modes: list[str]
    subscription_connected: bool = False
    api_key_connected: bool = False
    auth_mode: str = ""
    expires_at: float | None = None
    connected_at: float | None = None


class ConnectionList(_Camel):
    """GET /api/auth/status response: one ConnectionStatus per catalog card."""

    encryption_available: bool
    connections: list[ConnectionStatus] = []


class StartLoginResult(_Camel):
    flow: str
    auth_url: str | None = None
    user_code: str | None = None
    verification_uri: str | None = None
    # Poll cadence / lifetime for the device-code flow.
    interval_seconds: float | None = None
    expires_in_seconds: int | None = None


class PollLoginResult(_Camel):
    """POST /api/auth/{provider}/poll response."""
    status: str  # "pending" | "complete"
    # Server-suggested updated interval after a `slow_down`.
    interval_seconds: float | None = None
    # On complete: connection status fields.
    connected_at: float | None = None
    expires_at: float | None = None
    scope: str | None = None


class CompleteLoginRequest(_Camel):
    code: str


class ApiKeyRequest(_Camel):
    api_key: str | None = None
    base_url: str | None = None
    bearer: str | None = None


class ConnectionTestRequest(_Camel):
    model: str | None = None
