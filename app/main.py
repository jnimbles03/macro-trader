"""FastAPI app — unified market data hub."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.storage.migrations import init_schema
from app.api.v1 import router as v1_router

UI_DIR = Path(__file__).resolve().parent / "ui"
WEB_DIST = UI_DIR / "web" / "dist"

app = FastAPI(title="Macro Options Scout", version="0.3.0")

# v1 API — registered BEFORE the SPA catchall
app.include_router(v1_router, prefix="/api/v1")


@app.on_event("startup")
def _startup() -> None:
    try:
        init_schema()
    except Exception:
        pass


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


# --- React SPA ---------------------------------------------------------------
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def spa_root() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    def spa_catchall(full_path: str) -> FileResponse:
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
