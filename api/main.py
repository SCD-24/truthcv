"""FastAPI application: serves the wizard API and the built React bundle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp import types
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings

from agenttools.server import router as mcp_router
from agenttools.mcp_app import _TOOL_REGISTRY, _input_schema
from truth.store import data_dir

from .config import cors_origins, port, public_url, static_dir
from .routes import router

# Build MCP Server app for streamable-HTTP JSON-RPC endpoint
_mcp_server = Server(name="truthcv")
_mcp_http_app = _mcp_server.streamable_http_app(
    # Must match the path this app is reached at (the /mcp endpoint below
    # forwards the request scope verbatim, so scope["path"] is still "/mcp").
    streamable_http_path="/mcp",
    # The SDK's DNS-rebinding guard defaults to allowing only the `host` below,
    # which would 421 the agent's real requests: it reaches this service as
    # http://app:8080/mcp (docker-compose.yml TRUTHCV_MCP_URL), so the Host
    # header is "app:8080", not 127.0.0.1. That guard exists to stop a browser
    # rebinding onto a localhost server; this endpoint is not browser-facing and
    # is reachable only from inside the compose network, so turn it off rather
    # than hard-code a host list that breaks on every rename.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
    json_response=True,
    stateless_http=True,
)

# Register MCP tool handlers on the server
async def _handle_list_tools(ctx, params) -> types.ListToolsResult:
    """Return the list of available tools.

    The SDK dispatches request handlers as ``handler(ctx, params)``; both
    arguments are unused here because the tool list is static.
    """
    tools = [
        types.Tool(
            name=name,
            description=description,
            inputSchema=_input_schema(fn),
        )
        for name, (fn, description) in _TOOL_REGISTRY.items()
    ]
    return types.ListToolsResult(tools=tools)

async def _handle_call_tool(ctx, params) -> types.CallToolResult:
    """Call a registered tool by name.

    The SDK dispatches request handlers as ``handler(ctx, params)``, where
    ``params`` carries the tool name and arguments.
    """
    if params.name not in _TOOL_REGISTRY:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Unknown tool '{params.name}'.",
                )
            ],
            isError=True,
        )

    fn, _ = _TOOL_REGISTRY[params.name]
    try:
        result = fn(**(params.arguments or {}))
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=str(result),
                )
            ]
        )
    except Exception as e:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=str(e),
                )
            ],
            isError=True,
        )

# The SDK validates the incoming `params` member against the type given here
# and hands the handler the result, so these must be the *params* models.
# Passing the whole request model (CallToolRequest) rejects every call with
# -32602 before the handler is reached, because the payload under `params`
# carries no nested `params` member for it to bind.
_mcp_server.add_request_handler(
    "tools/list", types.PaginatedRequestParams, _handle_list_tools
)
_mcp_server.add_request_handler(
    "tools/call", types.CallToolRequestParams, _handle_call_tool
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run the MCP streamable-HTTP session manager for the app's lifetime.

    StreamableHTTPSessionManager.run() is what creates the task group every
    POST /mcp is dispatched through; without it each request raises
    "Task group is not initialized".
    """
    async with _mcp_server.session_manager.run():
        yield

app = FastAPI(title="TruthCV", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(mcp_router)

from api.browser_stream import relay as _browser_relay  # noqa: E402


@app.websocket("/api/browser/session/stream")
async def browser_session_stream(websocket: WebSocket) -> None:
    """noVNC relay for the attended sign-in session. See api/browser_stream.py."""
    await _browser_relay(websocket)

# Register the MCP streamable-HTTP JSON-RPC endpoint here (before _mount_static)
# to ensure it takes precedence over the SPA fallback.
@app.api_route("/mcp", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "TRACE"])
async def mcp_json_rpc_endpoint(request: Request):
    """MCP streamable-HTTP JSON-RPC endpoint."""
    # Forward the request to the MCP ASGI app
    responses = []
    
    async def receive():
        # Return request body on first call
        if not hasattr(receive, "called"):
            receive.called = True
            body = await request.body()
            return {
                "type": "http.request",
                "body": body,
                "more_body": False,
            }
        # End of stream
        return {"type": "http.disconnect"}
    
    async def send(message):
        responses.append(message)
    
    # Call the ASGI app with the request scope
    await _mcp_http_app(request.scope, receive, send)
    
    # Reconstruct response from collected messages
    status_code = 200
    headers = {}
    body_parts = []
    
    for message in responses:
        if message["type"] == "http.response.start":
            status_code = message["status"]
            # Headers come as tuples of bytes: [(b'name', b'value'), ...]
            # Convert to dict with string keys/values
            raw_headers = message.get("headers", [])
            headers = {
                name.decode("latin-1"): value.decode("latin-1")
                for name, value in raw_headers
            }
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))
    
    body = b"".join(body_parts)
    return StreamingResponse(iter([body]), status_code=status_code, headers=headers)


@app.get("/api/download/{name}")
def download(name: str) -> FileResponse:
    """Serve a generated file from the data volume (rendered CVs)."""
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    path = data_dir() / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(str(path), filename=name)


def _mount_static() -> None:
    """Mount the built frontend with SPA fallback, if the bundle exists."""
    root = static_dir()
    if not root.exists():
        return

    assets = root / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:  # noqa: ANN001
        # Don't serve SPA for /api or /mcp paths
        if full_path.startswith("api/") or full_path.startswith("mcp"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = root / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        index = root / "index.html"
        if not index.exists():
            raise HTTPException(status_code=404, detail="Frontend bundle not built.")
        return FileResponse(str(index))


_mount_static()


def main() -> None:  # pragma: no cover
    import uvicorn

    print(f"TruthCV is running at {public_url()}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port())


if __name__ == "__main__":  # pragma: no cover
    main()
