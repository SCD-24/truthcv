"""API-backed job-board key management (status, save, live test).

Lives in services so the ``/api/job-boards/{source}/key`` routes only shape the
response. Raises ``truthcv.services.errors`` types the global handler maps to the same
statuses the handlers returned before the move.
"""

from __future__ import annotations

import truthcv.infra.secretstore as secretstore
from truthcv.services.errors import BadRequest, NotFound


def _require_key_board(source: str) -> None:
    """Raise NotFound unless ``source`` is an API-backed board that needs a key."""
    from truthcv.domain.agentconfig import boards

    if not boards.requires_key(source):
        raise NotFound(f"'{source}' is not an API-backed job board that needs a key.")


def key_status(source: str) -> dict:
    """Whether an API-backed board has a key saved. The key itself is never returned.

    Returns source, key_set and encryption_available. NotFound when the board
    needs no key.
    """
    from truthcv.domain.jobfeeds import remoterocketship

    _require_key_board(source)
    return {
        "source": remoterocketship.SOURCE,
        "key_set": bool(remoterocketship.api_key()),
        "encryption_available": secretstore.encryption_available(),
    }


def set_key(source: str, api_key: str) -> dict:
    """Save (or, with an empty string, clear) an API-backed board's key.

    NotFound when the board needs no key; BadRequest when no ENCRYPTION_KEY is
    configured. Returns the same shape as key_status.
    """
    from truthcv.domain.jobfeeds import remoterocketship

    _require_key_board(source)
    if not secretstore.encryption_available():
        raise BadRequest("Set ENCRYPTION_KEY in .env first.")
    value = api_key.strip()
    secretstore.set_connection(remoterocketship.SOURCE, {"apiKey": value or None})
    return {
        "source": remoterocketship.SOURCE,
        "key_set": bool(remoterocketship.api_key()),
        "encryption_available": True,
    }


def test_key(source: str) -> tuple[bool, str]:
    """Verify the saved key with one live request against the board's API.

    NotFound when the board needs no key. Returns (ok, detail).
    """
    from truthcv.domain.jobfeeds import remoterocketship

    _require_key_board(source)
    return remoterocketship.check_key(remoterocketship.api_key())
