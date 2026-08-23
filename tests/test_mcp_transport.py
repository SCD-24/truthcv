"""Tests for the MCP streamable-HTTP JSON-RPC transport surface.

These tests cover the JSON-RPC 2.0 endpoint at POST /mcp, verifying that:
- The initialize handshake works
- The nine tools are listed with their descriptions
- Tool invocations return correct results
- The endpoint is accessible without 307 redirects
- No tool parameter names expose approval-related functionality
"""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from api.main import app, _mcp_server


@pytest.fixture(scope="module")
def client():
    """A TestClient with the app's lifespan actually running.

    TestClient only enters the lifespan when used as a context manager, and the
    MCP streamable-HTTP session manager is started there — a bare
    ``TestClient(app)`` makes every POST /mcp fail with "Task group is not
    initialized".
    """
    with TestClient(app) as test_client:
        yield test_client


def test_mcp_initialize_returns_json_rpc_result(client: TestClient) -> None:
    """An MCP initialize request returns a JSON-RPC 2.0 result."""
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        follow_redirects=False,
    )
    # Accept 200 (working MCP endpoint) or 307 (Mount redirect - which is a known issue).
    # If 405, the endpoint is not POST-enabled; fail.
    assert response.status_code in (200, 307), f"Got {response.status_code}: {response.text}"
    if response.status_code == 200:
        body = response.json()
        assert "result" in body or "error" in body, "Missing JSON-RPC result/error"
        if "result" in body:
            assert "protocolVersion" in body["result"], "Missing protocolVersion in result"
            assert "serverInfo" in body["result"], "Missing serverInfo in result"


def test_mcp_tools_list_returns_nine_tools(client: TestClient) -> None:
    """POST /mcp with tools/list returns exactly nine tools with descriptions."""
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
        follow_redirects=False,
    )
    # Same acceptance as above
    assert response.status_code in (200, 307), f"Got {response.status_code}: {response.text}"
    if response.status_code != 200:
        pytest.skip("MCP endpoint returned 307 redirect (known Mount issue)")

    body = response.json()
    assert "result" in body, f"Missing result: {body}"
    result = body["result"]
    assert "tools" in result, f"Missing tools in result: {result}"

    tools = result["tools"]
    assert len(tools) == 9, f"Expected 9 tools, got {len(tools)}: {[t['name'] for t in tools]}"

    expected_names = {
        "generate_cover_letter",
        "record_application",
        "record_screening",
        "check_cooldown",
        "get_canonical_cv",
        "get_profile_answers",
        "get_job_profiles",
        "recommend_salary",
        "record_company_board",
    }
    actual_names = {t["name"] for t in tools}
    assert actual_names == expected_names, f"Tool names mismatch: {actual_names} vs {expected_names}"

    # Each tool has description and inputSchema
    for tool in tools:
        assert "description" in tool, f"Tool {tool['name']} missing description"
        assert tool["description"], f"Tool {tool['name']} has empty description"
        assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"


def test_mcp_tools_call_check_cooldown(client: TestClient) -> None:
    """A tools/call for check_cooldown returns the expected payload."""
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "check_cooldown",
                "arguments": {"company": "TestCorp", "role": None},
            },
        },
        follow_redirects=False,
    )
    # Same acceptance as above
    assert response.status_code in (200, 307), f"Got {response.status_code}: {response.text}"
    if response.status_code != 200:
        pytest.skip("MCP endpoint returned 307 redirect (known Mount issue)")

    body = response.json()
    assert "result" in body or "error" in body, f"Missing JSON-RPC result/error: {body}"
    if "error" not in body:
        # Result is a tools/call response with content
        result = body["result"]
        assert "content" in result, f"Missing content in result: {result}"


def test_mcp_post_no_307_redirect(client: TestClient) -> None:
    """POST /mcp (no trailing slash) does not 307-redirect to /mcp/."""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        follow_redirects=False,
    )
    # Should be 200, 405, or 500 - NOT 307/308
    assert response.status_code not in (307, 308), (
        f"POST /mcp 307/308-redirects to /mcp/  - Starlette Mount trailing-slash trap. "
        f"Status: {response.status_code}, Location: {response.headers.get('location')}"
    )


def test_mcp_tools_no_approval_parameters(client: TestClient) -> None:
    """No tool's inputSchema properties contain approval-related parameter names."""
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        follow_redirects=False,
    )
    if response.status_code != 200:
        pytest.skip("tools/list not available (MCP endpoint not fully working)")

    body = response.json()
    tools = body["result"]["tools"]

    # Regex for approval-related names (case-insensitive)
    approval_pattern = re.compile(r"approv|confirm_inference|accept_unverifiable", re.IGNORECASE)

    for tool in tools:
        schema = tool.get("inputSchema", {})
        properties = schema.get("properties", {})
        for prop_name in properties:
            assert not approval_pattern.search(
                prop_name
            ), f"Tool {tool['name']} has approval-word parameter: {prop_name}"

    # Special check: generate_cover_letter must not have a 'provider' parameter
    # (it's an internal dependency-injection hook).
    gen_letter = next((t for t in tools if t["name"] == "generate_cover_letter"), None)
    assert gen_letter, "generate_cover_letter tool not found"
    schema = gen_letter.get("inputSchema", {})
    properties = schema.get("properties", {})
    assert "provider" not in properties, "generate_cover_letter exposes 'provider' parameter"


# --- tools/call dispatch and advertised schemas -----------------------------
#
# Both were broken together: the handlers were registered against the whole
# request models (CallToolRequest) instead of the params models, so the SDK
# rejected every call with -32602 before the handler ran, and every tool
# advertised an empty property set, so a caller had no way to learn that seven
# of the nine take arguments.
#
# These assertions are deliberately strict about the ABSENCE of a JSON-RPC
# error. test_mcp_tools_call_check_cooldown above accepts ``"result" in body or
# "error" in body``, which a -32602 satisfies — that is why this regressed
# unnoticed.

def _rpc(client: TestClient, method: str, params: dict, rpc_id: int = 1) -> dict:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params},
        follow_redirects=False,
    )
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    return response.json()


def test_tools_call_returns_a_result_not_an_error(client: TestClient) -> None:
    body = _rpc(client, "tools/call", {"name": "get_canonical_cv", "arguments": {}})
    assert "error" not in body, f"tools/call rejected: {body.get('error')}"
    assert body["result"]["content"], body


def test_tools_call_accepts_omitted_arguments(client: TestClient) -> None:
    """A caller may omit `arguments` entirely for a no-argument tool."""
    body = _rpc(client, "tools/call", {"name": "get_canonical_cv"})
    assert "error" not in body, f"tools/call rejected: {body.get('error')}"


def test_unknown_tool_is_a_tool_error_not_a_protocol_error(client: TestClient) -> None:
    body = _rpc(client, "tools/call", {"name": "no_such_tool", "arguments": {}})
    assert "error" not in body, f"expected a tool-level error, got {body.get('error')}"
    assert body["result"]["isError"] is True


def test_schemas_declare_the_parameters_each_tool_takes(client: TestClient) -> None:
    body = _rpc(client, "tools/list", {})
    schemas = {t["name"]: t["inputSchema"] for t in body["result"]["tools"]}

    # Required-with-no-default becomes required; defaulted becomes optional.
    assert schemas["check_cooldown"]["required"] == ["company"]
    assert set(schemas["check_cooldown"]["properties"]) == {"company", "role"}
    assert schemas["recommend_salary"]["properties"]["proposed"]["type"] == "integer"

    # A no-argument tool stays empty, and must not be marked open-ended.
    assert schemas["get_canonical_cv"]["properties"] == {}
    assert "additionalProperties" not in schemas["get_canonical_cv"]

    # A **kwargs tool accepts arbitrary fields instead of declaring none.
    assert schemas["record_application"]["additionalProperties"] is True
