"""Golden snapshot of the generated OpenAPI document.

Guards the Phase 3b refactor (moving business logic out of the route handlers
into truthcv/services/) against any HTTP surface change. URL paths, methods, parameter
and body schemas, response models and status codes all appear in
``truthcv.adapters.http.main.app.openapi()``, so a diff here means the wire contract moved.

The fixture is generated from the code, never hand-written. To regenerate
after an intended HTTP change, run:

    UPDATE_OPENAPI_SNAPSHOT=1 pytest tests/test_openapi_snapshot.py

Only that env var makes the test write the fixture. The default run never does.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
from pathlib import Path

import pytest

from truthcv.adapters.http.main import app

FIXTURE = Path(__file__).parent / "fixtures" / "openapi_snapshot.json"
UPDATE_ENV = "UPDATE_OPENAPI_SNAPSHOT"
MAX_DIFF_LINES = 200


def _render(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, indent=2) + "\n"


def _normalise(doc: dict) -> dict:
    """Blank operationIds that occur more than once in ``doc``.

    /mcp and /mcp/diagnostics in truthcv/adapters/http/main.py are registered with
    ``@app.api_route`` over 8 methods, so FastAPI emits the same operationId for
    several operations and PYTHONHASHSEED decides which method's id survives.
    Only duplicated ids are blanked; every unique id is compared exactly.
    """
    ops = [
        op
        for item in doc.get("paths", {}).values()
        for op in item.values()
        if isinstance(op, dict) and "operationId" in op
    ]
    counts: dict[str, int] = {}
    for op in ops:
        counts[op["operationId"]] = counts.get(op["operationId"], 0) + 1
    out = copy.deepcopy(doc)
    for item in out.get("paths", {}).values():
        for op in item.values():
            if isinstance(op, dict) and counts.get(op.get("operationId"), 0) > 1:
                op["operationId"] = ""
    return out


def _diff(golden: dict, live: dict) -> str:
    lines = difflib.unified_diff(
        _render(golden).splitlines(),
        _render(live).splitlines(),
        "golden",
        "live",
        lineterm="",
        n=2,
    )
    shown = list(lines)[:MAX_DIFF_LINES]
    return "\n".join(shown)


def test_openapi_matches_golden_snapshot():
    live = app.openapi()
    if os.environ.get(UPDATE_ENV) == "1":
        FIXTURE.write_text(_render(live), encoding="utf-8")
        return
    golden = _normalise(json.loads(FIXTURE.read_text(encoding="utf-8")))
    live = _normalise(live)
    if golden != live:
        pytest.fail(
            "OpenAPI document differs from tests/fixtures/openapi_snapshot.json. "
            "If the HTTP change is intended, regenerate with "
            f"{UPDATE_ENV}=1 pytest tests/test_openapi_snapshot.py.\n" + _diff(golden, live)
        )
