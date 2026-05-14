"""FastAPI app: JSON API for the React SPA + legacy Jinja routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.data.index_snapshot import get_mock_snapshot, get_snapshot
from app.reports.brief_json import brief_to_dict
from app.reports.markdown_renderer import render_brief
from app.reports.trade_report import generate_trade_brief
from app.storage.migrations import init_schema
from app.api.v1 import router as v1_router

UI_DIR = Path(__file__).resolve().parent / "ui"
WEB_DIST = UI_DIR / "web" / "dist"
TEMPLATES = Jinja2Templates(directory=str(UI_DIR / "templates"))

app = FastAPI(title="Macro Options Scout", version="0.3.0")
app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")

# Register v1 API router FIRST — before SPA catchall
app.include_router(v1_router)


@app.on_event("startup")
def _startup() -> None:
    try:
        init_schema()
    except Exception:
        pass


@app.get("/api/brief")
def api_brief(lookback: int = 24, market: str = "", fresh: bool = False) -> JSONResponse:
    brief = generate_trade_brief(
        lookback_hours=lookback,
        market_filter=market or None,
        fresh=bool(fresh),
    )
    return JSONResponse(brief_to_dict(brief))


@app.get("/api/snapshot")
def api_snapshot() -> JSONResponse:
    if get_settings().mock_data:
        return JSONResponse(get_mock_snapshot())
    return JSONResponse(get_snapshot())


@app.get("/poke", response_class=HTMLResponse)
def poke(request: Request, lookback: int = 24, market: str = "", fresh: bool = False):
    brief = generate_trade_brief(
        lookback_hours=lookback,
        market_filter=market or None,
        fresh=bool(fresh),
    )
    return TEMPLATES.TemplateResponse("report.html", {
        "request": request,
        "brief_md": render_brief(brief),
        "generated_at": brief.generated_at.isoformat(),
    })


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
else:
    @app.get("/", response_class=HTMLResponse)
    def index_fallback(request: Request):
        return TEMPLATES.TemplateResponse("index.html", {"request": request})
