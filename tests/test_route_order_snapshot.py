"""Golden snapshot of which FastAPI route serves each request.

What is locked:

* Check A: the set of leaf routes (class, full path, sorted methods, endpoint
  name) equals the fixture's exactly.
* Check B: for every pair of routes that one concrete request could match,
  the live app tries them in the same relative order as the fixture. The
  first full match wins, so that order decides which handler serves an
  overlapping path, e.g. ``/api/auth/gmail/...`` must stay ahead of
  ``/api/auth/{provider}/...``.

Why the full order is not locked: Phase 4 splits ``api/routes.py`` into one
``APIRouter`` per resource module, and ``api/routes.py`` becomes an aggregator
of ``include_router`` calls. That reorders routes that no single request can
match together, which cannot change which handler serves any request. Locking
matching behaviour, not file layout, lets that split land.

How overlap is computed (``_overlaps``): two routes overlap when they accept
a common protocol and HTTP method and their path templates unify. Methods are
compared exactly as recorded: Starlette ``Route`` adds HEAD to GET itself
(``starlette/routing.py`` L233-234), FastAPI's ``APIRoute`` does not
(``fastapi/routing.py`` L1026-1027), and both matchers test plain membership
(``starlette/routing.py`` L250, ``fastapi/routing.py`` L1508-1510), so a HEAD
request matches a GET-only ``APIRoute`` only partially (405) and HEAD is not
treated as implied by GET. Templates are split on ``/`` and unified segment by
segment against the Starlette convertor regexes (``starlette/convertors.py``).
Pairs whose methods are disjoint are not locked even when their paths unify:
order there only picks which route's ``Allow`` header a 405 carries, never
which handler runs.

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

The SPA catch-all ``GET /{full_path:path}`` and the ``/assets`` StaticFiles
``Mount`` in ``api/main.py`` (``_mount_static``) are registered only when the
built frontend bundle exists at import time, so they are absent from the test
app and from the fixture. ``_overlaps`` still handles both shapes.

The fixture is generated from commit f1e985b, never hand-written. To
regenerate after an intended routing change, write
``json.dumps(_route_order(), indent=2) + "\\n"`` to
``tests/fixtures/route_order_snapshot.json``.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest
from fastapi.routing import _IncludedRouter
from fastapi.testclient import TestClient
from starlette.convertors import CONVERTOR_TYPES
from starlette.routing import PARAM_REGEX

import services.gmail as gmail_service
from api.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "route_order_snapshot.json"

_ALL_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"})
_WEBSOCKET_CLASSES = {"APIWebSocketRoute", "WebSocketRoute"}
_MOUNT_CLASSES = {"Mount", "Host"}
_PATH = object()  # a {x:path} segment: matches ".*", slashes included


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


def _segment(raw: str):
    # A segment holding a path convertor anywhere is widened to _PATH (a
    # superset of what it matches). Every other segment becomes the regex
    # Starlette compiles for it: literal text escaped, params by convertor.
    if any(m.group(2) == ":path" for m in PARAM_REGEX.finditer(raw)):
        return _PATH
    pattern, last = "", 0
    for m in PARAM_REGEX.finditer(raw):
        pattern += re.escape(raw[last : m.start()])
        pattern += f"(?:{CONVERTOR_TYPES[(m.group(2) or ':str')[1:]].regex})"
        last = m.end()
    if last == 0:
        return raw  # plain literal
    return re.compile(pattern + re.escape(raw[last:]))


def _segments(path: str) -> list:
    return [_segment(s) for s in path.split("/")]


def _segment_overlaps(a, b) -> bool:
    # Literal vs literal: equal text. Literal vs param: the convertor regex
    # decides, which proves e.g. {x:int} cannot match "approvals". Param vs
    # param: assumed to overlap (conservative; str/int/uuid/float all share
    # some value).
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, str):
        return b.fullmatch(a) is not None
    if isinstance(b, str):
        return a.fullmatch(b) is not None
    return True


def _unify(a: list, b: list) -> bool:
    if not a or not b:
        return not a and not b
    if a[0] is _PATH or b[0] is _PATH:
        # ".*" spans one or more "/"-separated segments of the other side
        # (each possibly empty); Starlette's path regex is ".*", so
        # "/x/{p:path}" also matches "/x/" (p == "").
        if a[0] is _PATH and any(_unify(a[1:], b[k:]) for k in range(1, len(b) + 1)):
            return True
        return b[0] is _PATH and any(_unify(a[j:], b[1:]) for j in range(1, len(a) + 1))
    return _segment_overlaps(a[0], b[0]) and _unify(a[1:], b[1:])


def _accepts(entry: dict) -> set[tuple[str, str]]:
    # WebSocket routes carry methods None and match only websocket scopes, so
    # they overlap only other WebSocket routes (or a Mount). A Mount matches
    # every http method and websocket under its prefix
    # (starlette/routing.py Mount.matches, L387-418).
    cls = entry["class"]
    if cls in _WEBSOCKET_CLASSES:
        return {("websocket", "")}
    methods = _ALL_METHODS if entry["methods"] is None else entry["methods"]
    accepted = {("http", m) for m in methods}
    if cls in _MOUNT_CLASSES:
        accepted.add(("websocket", ""))
    return accepted


def _template(entry: dict) -> str:
    if entry["class"] in _MOUNT_CLASSES:
        return entry["path"].rstrip("/") + "/{path:path}"
    return entry["path"]


def _overlaps(a: dict, b: dict) -> bool:
    """True when one concrete request could fully match both routes."""
    if not _accepts(a) & _accepts(b):
        return False
    return _unify(_segments(_template(a)), _segments(_template(b)))


def _key(entry: dict) -> tuple:
    methods = entry["methods"]
    return (entry["class"], entry["path"], tuple(methods) if methods is not None else None, entry["endpoint"])


def _overlapping_pairs(entries: list[dict]) -> list[tuple[dict, dict]]:
    return [(a, b) for a, b in combinations(entries, 2) if _overlaps(a, b)]


def _golden() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_route_set_matches_golden_snapshot():
    golden = Counter(_key(e) for e in _golden())
    live = Counter(_key(e) for e in _route_order())
    missing = sorted((golden - live).elements(), key=repr)
    extra = sorted((live - golden).elements(), key=repr)
    assert not missing and not extra, (
        "Leaf route set differs from tests/fixtures/route_order_snapshot.json.\n"
        f"missing (in fixture, not live): {missing!r}\n"
        f"extra (live, not in fixture): {extra!r}"
    )


def test_overlapping_routes_keep_golden_relative_order():
    golden = _golden()
    keys = [_key(e) for e in golden]
    assert len(set(keys)) == len(keys), "fixture has duplicate leaf entries; order is ambiguous"
    live_index = {_key(e): i for i, e in enumerate(_route_order())}
    failures = []
    for first, second in _overlapping_pairs(golden):
        a, b = _key(first), _key(second)
        if a in live_index and b in live_index and live_index[a] > live_index[b]:
            failures.append(
                f"{a!r} vs {b!r}: fixture tries {first['endpoint']} before {second['endpoint']}, "
                f"live tries {second['endpoint']} before {first['endpoint']}"
            )
    assert not failures, "Overlapping routes changed relative order:\n" + "\n".join(failures)


def _route(path: str, *methods: str, cls: str = "APIRoute") -> dict:
    return {"class": cls, "path": path, "methods": sorted(methods) or None, "endpoint": None}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (_route("/api/screenings/approvals", "PATCH"), _route("/api/screenings/{screening_id}", "PATCH"), True),
        (
            _route("/api/company-findings/contradictions", "GET"),
            _route("/api/company-findings/{company}", "GET"),
            True,
        ),
        (_route("/api/auth/gmail/start", "POST"), _route("/api/auth/{provider}/start", "POST"), True),
        (_route("/api/auth/claude/complete", "POST"), _route("/api/auth/{provider}/complete", "POST"), True),
        (_route("/api/runs", "GET"), _route("/api/screenings", "GET"), False),
        (_route("/api/screenings/{screening_id}", "GET"), _route("/api/screenings/{screening_id}", "PATCH"), False),
        (_route("/{full_path:path}", "GET"), _route("/api/runs/{run_id}/urls", "GET"), True),
        (_route("/{full_path:path}", "GET"), _route("/", "GET"), True),
        (_route("/api/x/{rest:path}", "GET"), _route("/api/x", "GET"), False),
        (_route("/api/runs/{run_id:int}", "GET"), _route("/api/runs/latest", "GET"), False),
        (_route("/api/runs/{run_id:int}", "GET"), _route("/api/runs/42", "GET"), True),
        (_route("/assets", cls="Mount"), _route("/assets/app.js", "GET"), True),
        (_route("/api/browser/session/stream", cls="APIWebSocketRoute"), _route("/api/browser/session/stream", "GET"), False),
    ],
)
def test_overlap_detector(a, b, expected):
    assert _overlaps(a, b) is expected
    assert _overlaps(b, a) is expected


def test_overlap_detector_finds_known_fixture_pairs():
    pairs = {(a["endpoint"], b["endpoint"]) for a, b in _overlapping_pairs(_golden())}
    by_path = {(e["path"], tuple(e["methods"] or ())): e["endpoint"] for e in _golden()}
    known = [
        (("/api/screenings/approvals", "PATCH"), ("/api/screenings/{screening_id}", "PATCH")),
        (("/api/company-findings/contradictions", "GET"), ("/api/company-findings/{company}", "GET")),
        (("/api/auth/gmail/start", "POST"), ("/api/auth/{provider}/start", "POST")),
        (("/api/auth/claude/complete", "POST"), ("/api/auth/{provider}/complete", "POST")),
    ]
    for (p1, m1), (p2, m2) in known:
        pair = (by_path[(p1, (m1,))], by_path[(p2, (m2,))])
        assert pair in pairs or pair[::-1] in pairs, pair


def test_gmail_start_is_matched_before_generic_provider_start(data_dir):
    # POST /api/auth/gmail/start also fits /api/auth/{provider}/start. Only the
    # gmail handler is gated on Gmail tracking, so its distinctive 403 detail
    # proves it won the match (no network: the gate fails before any call).
    assert not gmail_service.tracking_enabled()
    r = TestClient(app).post("/api/auth/gmail/start")
    assert r.status_code == 403
    assert "Gmail response-tracking" in r.json()["detail"]
