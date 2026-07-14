"""FastAPI application: serves the wizard API and the built React bundle."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from truth.store import data_dir

from .config import cors_origins, port, static_dir
from .routes import router

app = FastAPI(title="TruthCV", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


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
