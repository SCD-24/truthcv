"""FastAPI application: serves the wizard API and the built React bundle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from mcp import types
from mcp.server import Server

from agenttools.server import router as mcp_router
from agenttools.mcp_app import _TOOL_REGISTRY
from truth.store import data_dir

from .config import cors_origins, port, static_dir
from .routes import router

# Build MCP Server app for streamable-HTTP JSON-RPC endpoint
_mcp_server = Server(name="truthcv")
_mcp_http_app = _mcp_server.streamable_http_app(
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
)

# Register MCP tool handlers on the server
async def _handle_list_tools(request: types.ListToolsRequest) -> types.ListToolsResult:
    """Return the list of available tools."""
    tools = []
    for name, (fn, description) in _TOOL_REGISTRY.items():
        input_schema = {
            "type": "object",
            "properties": {},
            "required": [],
        }
        tools.append(
            types.Tool(
                name=name,
                description=description,
                inputSchema=input_schema,
            )
        )
    return types.ListToolsResult(tools=tools)

async def _handle_call_tool(request: types.CallToolRequest) -> types.CallToolResult:
    """Call a registered tool by name."""
    if request.params.name not in _TOOL_REGISTRY:
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text",
                    text=f"Unknown tool '{request.params.name}'.",
                )
            ],
            isError=True,
        )
    
    fn, _ = _TOOL_REGISTRY[request.params.name]
    try:
        result = fn(**request.params.arguments)
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

_mcp_server.add_request_handler("tools/list", types.ListToolsRequest, _handle_list_tools)
_mcp_server.add_request_handler("tools/call", types.CallToolRequest, _handle_call_tool)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Attach MCP server lifespan to FastAPI app."""
    async with _mcp_server.lifespan():
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

    uvicorn.run(app, host="0.0.0.0", port=port())


if __name__ == "__main__":  # pragma: no cover
    main()
