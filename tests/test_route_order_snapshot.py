"""Golden snapshot of the order in which the FastAPI app matches routes.

The first matching route wins, so position decides which handler serves an
overlapping path, e.g. ``/api/auth/gmail/...`` must stay ahead of
``/api/auth/{provider}/...``. Splitting ``api/routes.py`` into sub-routers
nests the routes inside ``_IncludedRouter`` wrappers, so ``app.routes`` itself
locks nothing. The snapshot instead flattens to leaf routes in the order the
matcher tries them.

Matcher source relied on (installed fastapi, venv site-packages):
``fastapi/routing.py`` ``APIRouter.app`` (~L2690-2735) iterates ``self.routes``
then falls through to ``_match_low_priority``; an ``_IncludedRouter`` candidate
is entered via ``_IncludedRouter._match`` (L1698-1731), which iterates
``effective_candidates()`` (L1583-1602, prefix-combined children in
registration order, nested ``_IncludedRouter`` kept in place); low priority
routes come from ``_iter_low_priority_routes`` (L2752-2758).

Entries are leaf routes only: class, full path, sorted methods, endpoint name.
Nesting depth, wrappers and endpoint modules are deliberately not recorded
because they change on purpose when routers move.

The fixture is generated from the code, never hand-written. To regenerate after
an intended routing change, write ``json.dumps(_route_order(), indent=2) + "\\n"``
to ``tests/fixtures/route_order_snapshot.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.routing import _IncludedRouter
from fastapi.testclient import TestClient

import services.gmail as gmail_service
from api.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "route_order_snapshot.json"


def _leaf(candidate) -> dict:
    # An _EffectiveRouteContext wraps the real route and carries the
    # include-prefixed path; a bare top-level route is its own leaf.
    original = getattr(candidate, "original_route", candidate)
    starlette = getattr(candidate, "starlette_route", None)
    path = getattr(candidate, "path", None) if starlette is None else starlette.path
    if not isinstance(path, str):
        path = getattr(original, "path", None)
    methods = getattr(original, "methods", None)
    endpoint = getattr(original, "endpoint", None)
    return {
        "class": type(original).__name__,
        "path": path,
        "methods": sorted(methods) if methods is not None else None,
        "endpoint": getattr(endpoint, "__name__", None),
    }


def _walk(routes) -> list[dict]:
    out: list[dict] = []
    for route in routes:
        if isinstance(route, _IncludedRouter):
            out.extend(_walk(route.effective_candidates()))
        else:
            out.append(_leaf(route))
    return out


def _route_order() -> list[dict]:
    router = app.router
    low = [_leaf(r) for r in router._iter_low_priority_routes()]
    return _walk(router.routes) + low


def test_route_order_matches_golden_snapshot():
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    live = _route_order()
    for index in range(max(len(golden), len(live))):
        expected = golden[index] if index < len(golden) else None
        actual = live[index] if index < len(live) else None
        if expected != actual:
            pytest.fail(
                f"Route order differs from tests/fixtures/route_order_snapshot.json "
                f"at index {index}: golden={expected!r} live={actual!r} "
                f"(golden has {len(golden)} routes, live has {len(live)})."
            )


def test_gmail_start_is_matched_before_generic_provider_start(data_dir):
    # POST /api/auth/gmail/start also fits /api/auth/{provider}/start. Only the
    # gmail handler is gated on Gmail tracking, so its distinctive 403 detail
    # proves it won the match (no network: the gate fails before any call).
    assert not gmail_service.tracking_enabled()
    r = TestClient(app).post("/api/auth/gmail/start")
    assert r.status_code == 403
    assert "Gmail response-tracking" in r.json()["detail"]
