"""Framework-free domain exceptions raised by the services layer.

Nothing here imports FastAPI. ``truthcv/adapters/http/main.py`` maps each of these to an
``HTTPException`` for the HTTP adapter; the MCP adapter's
``_handle_call_tool`` already catches any ``Exception`` and turns it into an
``isError=True`` result, so these need no special handling there.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for every domain exception raised by truthcv/services/*."""


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


class BadRequest(ServiceError):
    """The request is malformed or its input is invalid. Maps to HTTP 400.

    Exists so extracted route logic can keep the 400 its handlers returned
    before the move without importing FastAPI.
    """


class Forbidden(ServiceError):
    """The caller is not allowed to do this. Maps to HTTP 403.

    Exists so extracted route logic can keep the 403 its handlers returned
    before the move without importing FastAPI.
    """


class InternalError(ServiceError):
    """An unexpected server-side failure with a client-safe message. Maps to HTTP 500.

    Exists so extracted route logic can keep an explicit 500 detail string,
    rather than falling through to the handler's defensive default.
    """


class BadGateway(ServiceError):
    """An upstream dependency answered badly or not at all. Maps to HTTP 502.

    Exists so extracted route logic can keep the 502 its handlers returned
    before the move without importing FastAPI.
    """


class UpstreamRefused(ServiceError):
    """An upstream service refused the call; relay its answer unchanged.

    ``status`` and ``detail`` are the upstream HTTP status and detail, passed
    through verbatim, because some routes proxy a third party's status code
    (e.g. 401/429) and clients depend on seeing it.
    """

    def __init__(self, status: int, detail: dict | str):
        super().__init__(status, detail)
        self.status = status
        self.detail = detail
