"""Wire equivalence: a ServiceError must look exactly like the HTTPException it replaces."""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from api.main import _service_error_handler
from services import errors
from services.errors import ServiceError

CASES = [
    ("not_found", errors.NotFound("Not Found"), HTTPException(404, "Not Found")),
    ("conflict", errors.Conflict("dup", payload="dup"), HTTPException(409, "dup")),
    (
        "conflict_dict",
        errors.Conflict("dup", payload={"id": 7}),
        HTTPException(409, {"id": 7}),
    ),
    ("refused", errors.Refused("nope"), HTTPException(422, "nope")),
    ("unavailable", errors.Unavailable("down"), HTTPException(503, "down")),
    ("bad_request", errors.BadRequest("bad"), HTTPException(400, "bad")),
    ("forbidden", errors.Forbidden("no"), HTTPException(403, "no")),
    ("internal", errors.InternalError("boom"), HTTPException(500, "boom")),
    ("bad_gateway", errors.BadGateway("up"), HTTPException(502, "up")),
    (
        "upstream_401",
        errors.UpstreamRefused(401, "unauthorized"),
        HTTPException(401, "unauthorized"),
    ),
    (
        "upstream_429_dict",
        errors.UpstreamRefused(429, {"message": "slow"}),
        HTTPException(429, {"message": "slow"}),
    ),
]


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(ServiceError, _service_error_handler)
    for name, service_exc, http_exc in CASES:

        def raise_it(exc=service_exc):
            raise exc

        def raise_http(exc=http_exc):
            raise exc

        app.add_api_route(f"/svc/{name}", raise_it)
        app.add_api_route(f"/http/{name}", raise_http)
    return TestClient(app)


@pytest.mark.parametrize("name", [c[0] for c in CASES])
def test_service_error_matches_http_exception(name):
    client = _client()
    svc = client.get(f"/svc/{name}")
    http = client.get(f"/http/{name}")
    assert svc.status_code == http.status_code
    assert svc.json() == http.json()
    assert svc.headers["content-type"] == http.headers["content-type"]
