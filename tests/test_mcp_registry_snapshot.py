"""Golden snapshot of the agent MCP tool surface.

Guards MCP surface byte-identity during the Phase 3a services move. It pins
two registries against a committed fixture:

- ``agenttools.mcp_app._TOOL_REGISTRY``: each tool's name, description and the
  inputSchema that ``_input_schema(fn)`` derives from its signature.
- ``agenttools.server.TOOLS`` as exposed by ``list_tools()``: each REST tool's
  name and parameter names.

A change to what the agent is advertised fails here. The fixture is generated
from the code, never hand-written. To regenerate after an intended change:

    .venv/bin/python -c "import json; from tests.test_mcp_registry_snapshot import build_snapshot, FIXTURE; FIXTURE.write_text(json.dumps(build_snapshot(), sort_keys=True, indent=2) + '\\n', encoding='utf-8')"
"""

from __future__ import annotations

import difflib
import json
from pathlib import Path

import pytest

from agenttools.mcp_app import _TOOL_REGISTRY, _input_schema
from agenttools.server import list_tools

FIXTURE = Path(__file__).parent / "fixtures" / "mcp_registry_snapshot.json"


def build_snapshot() -> dict:
    """Rebuild the snapshot structure from the live code."""
    mcp_registry = {
        name: {"description": description, "inputSchema": _input_schema(fn)}
        for name, (fn, description) in _TOOL_REGISTRY.items()
    }
    rest_tools = {tool["name"]: {"params": tool["params"]} for tool in list_tools()["tools"]}
    return {"mcp_registry": mcp_registry, "rest_tools": rest_tools}


def _tool_json(entry: object) -> list[str]:
    return json.dumps(entry, sort_keys=True, indent=2).splitlines()


def test_mcp_surface_matches_golden_snapshot():
    golden = json.loads(FIXTURE.read_text(encoding="utf-8"))
    live = build_snapshot()
    failures = []
    for section in ("mcp_registry", "rest_tools"):
        expected, actual = golden[section], live[section]
        differing = [
            name
            for name in sorted(set(expected) | set(actual))
            if expected.get(name) != actual.get(name)
        ]
        if not differing:
            continue
        failures.append(f"{section}: {len(differing)} tool(s) differ from the golden snapshot")
        for name in differing:
            failures.append(f"--- {section}.{name}")
            failures.extend(
                difflib.unified_diff(
                    _tool_json(expected.get(name)),
                    _tool_json(actual.get(name)),
                    "golden",
                    "live",
                    lineterm="",
                )
            )
    if failures:
        pytest.fail("\n".join(failures), pytrace=False)
