"""FastAPI app exposing the local web UI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.reports.markdown_renderer import render_brief
from app.reports.trade_report import generate_trade_brief
from app.storage.migrations import init_schema

UI_DIR = Path(__file__).resolve().parent / "ui"
TEMPLATES = Jinja2Templates(directory=str(UI_DIR / "templates"))

app = FastAPI(title="Macro Options Scout", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    try:
        init_schema()
    except Exception:
        pass


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return TEMPLATES.TemplateResponse("index.html", {"request": request})


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
