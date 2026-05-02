"""Typer CLI for Macro Options Scout."""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timezone
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from app.config import SUPPORTED_ROOTS, get_settings
from app.data.cache import reset_cache
from app.data.news_ingest import fetch_recent_headlines
from app.reports.markdown_renderer import render_brief
from app.reports.trade_report import generate_trade_brief
from app.storage.migrations import init_schema
from app.storage.repository import (
    ingest_status,
    list_paper_trades,
    log_run,
    save_paper_trade,
)

app = typer.Typer(help="Macro Options Scout — research-only options trade ideas.", no_args_is_help=True)
console = Console()


# --------------------------------------------------------------------------
@app.command()
def poke(
    lookback: str = typer.Option("24h", help="Lookback window, e.g. 24h, 12h, 48h"),
    market: Optional[str] = typer.Option(None, help="rates|equity|commodities|fx"),
    risk_profile: str = typer.Option("balanced", help="conservative|balanced|aggressive|yolo"),
    fresh: bool = typer.Option(False, help="Bypass all caches"),
    live: bool = typer.Option(False, "--live", help="Bypass the data warehouse and hit vendor APIs directly"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Don't write to paper-trade log"),
    json_out: bool = typer.Option(False, "--json", help="Emit JSON instead of markdown"),
):
    """Pull last 24h of headlines and propose two trade ideas (or NO TRADE)."""
    init_schema()
    if fresh:
        reset_cache()

    hours = _parse_hours(lookback)
    brief = generate_trade_brief(
        lookback_hours=hours,
        market_filter=market,
        risk_profile=risk_profile,
        fresh=fresh,
        live=live,
    )

    if json_out:
        payload = {
            "generated_at": brief.generated_at.isoformat(),
            "regime": brief.regime.regime.value,
            "regime_confidence": brief.regime.confidence,
            "persona_top": brief.persona_top,
            "spread": brief.selector.spread.trade.model_dump() if brief.selector.spread.trade else None,
            "spread_no_trade_reason": brief.selector.spread.no_trade_reason.value if brief.selector.spread.no_trade_reason else None,
            "yolo": brief.selector.yolo.trade.model_dump() if brief.selector.yolo.trade else None,
            "yolo_no_trade_reason": brief.selector.yolo.no_trade_reason.value if brief.selector.yolo.no_trade_reason else None,
            "rejected": brief.selector.rejected,
        }
        typer.echo(json.dumps(payload, default=str, indent=2))
        return

    md = render_brief(brief)
    console.print(Markdown(md))

    if not dry_run:
        spread = brief.selector.spread.trade
        yolo = brief.selector.yolo.trade
        if spread is not None:
            save_paper_trade(spread, notes="auto-saved from poke (spread)")
        if yolo is not None:
            save_paper_trade(yolo, notes="auto-saved from poke (yolo)")
        log_run(
            regime=brief.regime.regime.value,
            persona_weights={n: w for n, w, _ in brief.persona_top},
            spread_summary=(spread.name if spread else "NO TRADE"),
            yolo_summary=(yolo.name if yolo else "NO TRADE"),
        )


# --------------------------------------------------------------------------
@app.command()
def headlines(lookback: str = typer.Option("24h", help="Lookback window")):
    """Show the last N hours of (deduped) headlines from the data warehouse."""
    init_schema()
    hours = _parse_hours(lookback)
    raw = fetch_recent_headlines(lookback_hours=hours)
    table = Table(title=f"Headlines (last {hours}h)")
    table.add_column("when", overflow="ellipsis")
    table.add_column("tier")
    table.add_column("source")
    table.add_column("title", overflow="fold")
    for h in raw[:80]:
        table.add_row(h.published_at.strftime("%Y-%m-%d %H:%M"), h.tier.value, h.source, h.title)
    console.print(table)


# --------------------------------------------------------------------------
@app.command("paper-log")
def paper_log(limit: int = typer.Option(20)):
    """Show recent paper trades."""
    init_schema()
    rows = list_paper_trades(limit=limit)
    table = Table(title="Paper trade log")
    table.add_column("opened_at")
    table.add_column("status")
    table.add_column("name (truncated)", overflow="ellipsis")
    for pt in rows:
        try:
            data = json.loads(pt.trade_idea_json)
            name = data.get("name", "?")
        except Exception:
            name = "?"
        table.add_row(pt.opened_at.isoformat(), pt.status.value, name)
    console.print(table)


# --------------------------------------------------------------------------
@app.command("backtest-signals")
def backtest_signals():
    """Placeholder for v1 — no historical backtest engine yet."""
    console.print("[yellow]backtest-signals[/yellow]: not implemented in v1; returns 0 hits.")


# --------------------------------------------------------------------------
@app.command("config-check")
def config_check():
    """Print effective config without revealing secret values."""
    s = get_settings()
    table = Table(title="Effective config")
    table.add_column("key")
    table.add_column("value")

    def _redact(v: str) -> str:
        return "set" if v else "unset"

    table.add_row("primary_model", s.grok_model)
    table.add_row("validator_model", s.anthropic_model)
    table.add_row("XAI_API_KEY", _redact(s.xai_api_key))
    table.add_row("ANTHROPIC_API_KEY", _redact(s.anthropic_api_key))
    table.add_row("FRED_API_KEY", _redact(s.fred_api_key))
    table.add_row("NEWSAPI_KEY", _redact(s.newsapi_key))
    table.add_row("MOCK_DATA", str(s.mock_data))
    table.add_row("PAPER_MODE", str(s.paper_mode))
    table.add_row("ALLOW_LIVE_TRADING", str(s.allow_live_trading))
    table.add_row("ALLOW_0DTE", str(s.allow_0dte))
    table.add_row("IBKR_ENABLED", str(s.ibkr_enabled))
    table.add_row("IBKR_PORT", str(s.ibkr_port))
    table.add_row("MIN_SPREAD_RR", f"{s.min_spread_rr:.2f}")
    table.add_row("YOLO_MAX_PREMIUM_DOLLARS", f"{s.yolo_max_premium_dollars:.2f}")
    table.add_row("supported roots", ", ".join(sorted(SUPPORTED_ROOTS)))
    console.print(table)
    if s.allow_live_trading:
        console.print("[red]ALLOW_LIVE_TRADING is true — agent still refuses; v1 is paper-only.[/red]")
        sys.exit(0)


# ==========================================================================
# Data warehouse — ingest commands
# ==========================================================================

@app.command("ingest-headlines")
def ingest_headlines(
    lookback: str = typer.Option("24h", help="Recent-mode lookback window"),
    backfill_from: Optional[str] = typer.Option(None, "--from", help="Backfill from YYYY-MM-DD"),
    backfill_to: Optional[str] = typer.Option(None, "--to", help="Backfill until YYYY-MM-DD (default: now)"),
    sources: str = typer.Option("gdelt,newsapi,rss", help="Comma-separated subset"),
):
    """Pull headlines from each enabled source into the warehouse."""
    init_schema()
    from app.ingest import gdelt, newsapi, rss
    from app.ingest.runner import run_one

    since = _parse_date(backfill_from)
    until = _parse_date(backfill_to)
    hours = _parse_hours(lookback)

    wanted = {s.strip().lower() for s in sources.split(",") if s.strip()}
    results = []
    if "gdelt" in wanted:
        results.append(run_one("gdelt", gdelt.ingest,
                                lookback_hours=hours, since=since, until=until))
    if "newsapi" in wanted:
        results.append(run_one("newsapi", newsapi.ingest,
                                lookback_hours=hours, since=since, until=until))
    if "rss" in wanted:
        results.append(run_one("rss", rss.ingest,
                                lookback_hours=hours, since=since, until=until))
    _print_ingest_table(results)


@app.command("ingest-fred")
def ingest_fred(
    backfill_from: Optional[str] = typer.Option(None, "--from", help="Backfill from YYYY-MM-DD"),
):
    """Pull FRED macro signals into the warehouse."""
    init_schema()
    from app.ingest import fred
    from app.ingest.runner import run_one

    since = _parse_date(backfill_from)
    res = run_one("fred", fred.ingest, since=since)
    _print_ingest_table([res])


@app.command("ingest-chains")
def ingest_chains(
    roots: str = typer.Option("ZN,ES", help="Comma-separated roots, e.g. ZN,ES,CL"),
    expiration: Optional[str] = typer.Option(None, help="Specific expiration YYYY-MM-DD (default: front-month)"),
):
    """Snapshot option chains from IBKR for the given roots."""
    init_schema()
    from app.ingest import ibkr_chain
    from app.ingest.runner import run_one

    results = []
    for r in [x.strip().upper() for x in roots.split(",") if x.strip()]:
        results.append(run_one(
            f"ibkr:{r}", ibkr_chain.ingest, root=r, expiration=expiration,
        ))
    _print_ingest_table(results)


@app.command("ingest-all")
def ingest_all(
    lookback: str = typer.Option("24h"),
    chains: bool = typer.Option(False, "--chains", help="Also pull option chains (requires IB Gateway)"),
    chain_roots: str = typer.Option("ZN,ES", help="Roots when --chains is on"),
):
    """Run every ingest job. Suitable target for cron / launchd."""
    init_schema()
    from app.ingest.runner import run_all

    hours = _parse_hours(lookback)
    roots = [r.strip().upper() for r in chain_roots.split(",") if r.strip()]
    results = run_all(
        lookback_hours=hours,
        include_chains=chains,
        chain_roots=roots,
    )
    _print_ingest_table(results)


@app.command("data-status")
def data_status():
    """Show last ingest per vendor + warehouse table sizes."""
    init_schema()
    info = ingest_status()

    per_vendor = info[0]["per_vendor"]
    table = Table(title="Last ingest per vendor")
    table.add_column("vendor")
    table.add_column("last completed")
    table.add_column("rows (success)", justify="right")
    table.add_column("runs", justify="right")
    if not per_vendor:
        table.add_row("(none yet)", "-", "-", "-")
    else:
        for r in per_vendor:
            table.add_row(
                r["vendor"],
                str(r["last_ok"] or "-"),
                str(r["total_rows_ok"] or 0),
                str(r["runs"]),
            )
    console.print(table)

    counts = info[1]["warehouse_counts"]
    sizes = Table(title="Warehouse table sizes")
    sizes.add_column("table")
    sizes.add_column("rows", justify="right")
    for k, v in counts.items():
        sizes.add_row(k, str(v))
    console.print(sizes)


# --------------------------------------------------------------------------
def _parse_hours(s: str) -> int:
    s = s.strip().lower()
    if s.endswith("h"):
        return int(s[:-1])
    return int(s)


def _parse_date(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except Exception:
        raise typer.BadParameter(f"Invalid date '{s}'; expected YYYY-MM-DD")


def _print_ingest_table(results) -> None:
    table = Table(title="Ingest results")
    table.add_column("vendor")
    table.add_column("status")
    table.add_column("rows added", justify="right")
    table.add_column("error", overflow="fold")
    for r in results:
        table.add_row(r.vendor, r.status, str(r.rows_added), r.error or "")
    console.print(table)


if __name__ == "__main__":
    app()
