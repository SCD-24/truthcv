"""Framework-free domain exceptions raised by the services layer.

Nothing here imports FastAPI. ``api/main.py`` maps each of these to an
``HTTPException`` for the HTTP adapter; the MCP adapter's
``_handle_call_tool`` already catches any ``Exception`` and turns it into an
``isError=True`` result, so these need no special handling there.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for every domain exception raised by services/*."""


class NotFound(ServiceError):
    """The requested resource does not exist. Maps to HTTP 404."""


class Conflict(ServiceError):
    """The request conflicts with existing state. Maps to HTTP 409.

    ``payload`` carries the structured detail the existing HTTP contract
    returns (e.g. the id of the existing record that caused the conflict) —
    it becomes the ``HTTPException.detail`` verbatim.
    """

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload if payload is not None else {"detail": message}


class Refused(ServiceError):
    """The request is well-formed but not acceptable. Maps to HTTP 422.

    ``reason`` is a short machine/human-readable string describing why; it is
    used as the ``HTTPException.detail`` unless the caller passes a richer
    structured payload.
    """

    def __init__(self, reason: str, payload: dict | str | None = None):
        super().__init__(reason)
        self.reason = reason
        self.payload = payload if payload is not None else reason


class Unavailable(ServiceError):
    """A required backend/dependency is unavailable. Maps to HTTP 503."""
