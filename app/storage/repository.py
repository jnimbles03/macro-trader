"""Repository functions over SQLite.

Two layers:
- Trading-bot artefacts (paper trades, run log) — write+read by the bot
- Data warehouse (headlines, macro_signals, option_chains, ingest_runs)
  — written by ingest jobs, read by trading bots
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from app.models.headline import CredibilityTier, Headline
from app.models.macro_signal import MacroSignal
from app.models.option_contract import OptionChain, OptionContract, OptionType
from app.models.paper_trade import PaperTrade, PaperTradeStatus
from app.models.trade_idea import TradeIdea
from app.storage.db import make_engine


# ---------------------------------------------------------------------------
# Trading-bot artefacts
# ---------------------------------------------------------------------------
def save_paper_trade(idea: TradeIdea, *, notes: str | None = None) -> PaperTrade:
    pt = PaperTrade(
        id=str(uuid.uuid4()),
        trade_idea_json=idea.model_dump_json(),
        opened_at=datetime.utcnow(),
        closed_at=None,
        status=PaperTradeStatus.OPEN,
        pnl=None,
        notes=notes,
    )
    eng = make_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO paper_trades (id, trade_idea_json, opened_at, status, notes)
            VALUES (:id, :j, :opened_at, :status, :notes)
        """), {"id": pt.id, "j": pt.trade_idea_json, "opened_at": pt.opened_at,
                "status": pt.status.value, "notes": pt.notes})
    return pt


def list_paper_trades(limit: int = 50) -> list[PaperTrade]:
    eng = make_engine()
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT id, trade_idea_json, opened_at, closed_at, status, pnl, notes
            FROM paper_trades ORDER BY opened_at DESC LIMIT :limit
        """), {"limit": limit}).fetchall()
    out: list[PaperTrade] = []
    for r in rows:
        out.append(PaperTrade(
            id=r[0],
            trade_idea_json=r[1],
            opened_at=r[2],
            closed_at=r[3],
            status=PaperTradeStatus(r[4]),
            pnl=r[5],
            notes=r[6],
        ))
    return out


def log_run(regime: str, persona_weights: dict, spread_summary: str, yolo_summary: str,
            *, notes: str | None = None) -> None:
    eng = make_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO run_log (ran_at, regime, persona_weights, spread_summary, yolo_summary, notes)
            VALUES (:ran_at, :regime, :pw, :ss, :ys, :notes)
        """), {"ran_at": datetime.utcnow(), "regime": regime,
                "pw": json.dumps(persona_weights), "ss": spread_summary, "ys": yolo_summary,
                "notes": notes})


def remember_headlines(headlines: list[dict]) -> None:
    if not headlines:
        return
    eng = make_engine()
    with eng.begin() as conn:
        for h in headlines:
            conn.execute(text("""
                INSERT OR IGNORE INTO headlines_seen (url, title, source, tier, published_at, category, seen_at)
                VALUES (:url, :title, :source, :tier, :published_at, :category, :seen_at)
            """), {**h, "seen_at": datetime.utcnow()})


# ---------------------------------------------------------------------------
# Data warehouse — headlines
# ---------------------------------------------------------------------------
def _canonical_url(u: str) -> str:
    try:
        p = urlparse(str(u))
        return f"{p.scheme}://{p.netloc}{p.path}".rstrip("/").lower()
    except Exception:
        return str(u).lower()


def upsert_headlines(rows: list[dict], vendor: str) -> int:
    """Insert headlines; returns count of newly-inserted rows.

    Each `row` must carry: url, title, source, tier, published_at; optionally
    country, region, category, summary, is_rumor, is_unsourced.

    If `category` is missing, we classify the title here so every downstream
    consumer gets a real channel (not 'other').
    """
    if not rows:
        return 0
    # Lazy import to avoid a cycle at module load.
    from app.analysis.headline_classifier import classify_channel

    now = datetime.utcnow()
    inserted = 0
    eng = make_engine()
    with eng.begin() as conn:
        for r in rows:
            category = r.get("category") or classify_channel(
                r.get("title", ""), r.get("summary")
            )
            params = {
                "url": str(r["url"]),
                "canonical_url": _canonical_url(r["url"]),
                "title": r["title"],
                "source": r["source"],
                "tier": r["tier"].value if hasattr(r["tier"], "value") else r["tier"],
                "published_at": r["published_at"],
                "country": r.get("country"),
                "region": r.get("region"),
                "category": category,
                "summary": r.get("summary"),
                "is_rumor": int(bool(r.get("is_rumor", False))),
                "is_unsourced": int(bool(r.get("is_unsourced", False))),
                "vendor": vendor,
                "ingested_at": now,
            }
            res = conn.execute(text("""
                INSERT OR IGNORE INTO headlines
                    (url, canonical_url, title, source, tier, published_at, country, region,
                     category, summary, is_rumor, is_unsourced, vendor, ingested_at)
                VALUES
                    (:url, :canonical_url, :title, :source, :tier, :published_at, :country, :region,
                     :category, :summary, :is_rumor, :is_unsourced, :vendor, :ingested_at)
            """), params)
            inserted += res.rowcount or 0
    return inserted


def query_headlines(*, since: datetime | None = None, until: datetime | None = None,
                    limit: int = 500) -> list[Headline]:
    eng = make_engine()
    where = []
    params: dict[str, Any] = {"limit": limit}
    if since is not None:
        where.append("published_at >= :since")
        params["since"] = since
    if until is not None:
        where.append("published_at <= :until")
        params["until"] = until
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT url, title, source, tier, published_at, country, region, category,
               summary, is_rumor, is_unsourced
        FROM headlines
        {where_sql}
        ORDER BY published_at DESC
        LIMIT :limit
    """
    out: list[Headline] = []
    with eng.begin() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    for r in rows:
        try:
            out.append(Headline(
                url=r[0],
                title=r[1],
                source=r[2],
                tier=CredibilityTier(r[3]),
                published_at=_ensure_aware(r[4]),
                country=r[5],
                region=r[6],
                category=r[7] or "other",
                summary=r[8],
                is_rumor=bool(r[9]),
                is_unsourced=bool(r[10]),
            ))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# Data warehouse — macro signals
# ---------------------------------------------------------------------------
def upsert_macro_signals(rows: list[dict], vendor: str = "fred") -> int:
    if not rows:
        return 0
    now = datetime.utcnow()
    inserted = 0
    eng = make_engine()
    with eng.begin() as conn:
        for r in rows:
            res = conn.execute(text("""
                INSERT OR IGNORE INTO macro_signals
                    (series_id, label, value, as_of, units, vendor, ingested_at)
                VALUES
                    (:series_id, :label, :value, :as_of, :units, :vendor, :ingested_at)
            """), {
                "series_id": r["series_id"],
                "label": r["label"],
                "value": float(r["value"]),
                "as_of": r["as_of"],
                "units": r.get("units"),
                "vendor": vendor,
                "ingested_at": now,
            })
            inserted += res.rowcount or 0
    return inserted


def latest_macro_signals() -> list[MacroSignal]:
    """Return the most recent observation per series."""
    eng = make_engine()
    sql = """
        SELECT series_id, label, value, as_of, units
        FROM macro_signals s1
        WHERE as_of = (
            SELECT MAX(as_of) FROM macro_signals s2 WHERE s2.series_id = s1.series_id
        )
        ORDER BY series_id
    """
    out: list[MacroSignal] = []
    with eng.begin() as conn:
        rows = conn.execute(text(sql)).fetchall()
    for r in rows:
        out.append(MacroSignal(
            series_id=r[0], label=r[1], value=r[2], as_of=_ensure_aware(r[3]), units=r[4],
        ))
    return out


# ---------------------------------------------------------------------------
# Data warehouse — option chains
# ---------------------------------------------------------------------------
def upsert_chain(chain: OptionChain, vendor: str = "ibkr") -> int:
    """Persist a chain snapshot. Returns the chain_id."""
    now = datetime.utcnow()
    eng = make_engine()
    with eng.begin() as conn:
        res = conn.execute(text("""
            INSERT INTO option_chains
                (root, underlying_symbol, underlying_price, expiration, quote_time,
                 multiplier, vendor, ingested_at)
            VALUES
                (:root, :sym, :px, :exp, :qt, :mult, :vendor, :ing)
        """), {
            "root": chain.root, "sym": chain.underlying_symbol,
            "px": chain.underlying_price, "exp": chain.expiration.isoformat(),
            "qt": chain.quote_time, "mult": chain.multiplier,
            "vendor": vendor, "ing": now,
        })
        chain_id = res.lastrowid
        for c in chain.contracts:
            conn.execute(text("""
                INSERT INTO option_contracts
                    (chain_id, option_type, strike, bid, ask, last, iv, delta, gamma,
                     theta, vega, volume, open_interest)
                VALUES
                    (:cid, :ot, :k, :b, :a, :l, :iv, :d, :g, :t, :v, :vol, :oi)
            """), {
                "cid": chain_id, "ot": c.option_type.value, "k": c.strike,
                "b": c.bid, "a": c.ask, "l": c.last, "iv": c.iv,
                "d": c.delta, "g": c.gamma, "t": c.theta, "v": c.vega,
                "vol": c.volume, "oi": c.open_interest,
            })
    return int(chain_id)


def list_expirations(root: str) -> list[str]:
    """Return all available expiration dates for a root, sorted ascending."""
    eng = make_engine()
    with eng.begin() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT expiration FROM option_chains
            WHERE root = :root
            ORDER BY expiration ASC
        """), {"root": root}).fetchall()
    return [r[0] for r in rows]


def latest_chain(root: str, expiration: date | None = None) -> OptionChain | None:
    eng = make_engine()
    where = "WHERE root = :root"
    params: dict[str, Any] = {"root": root}
    if expiration is not None:
        where += " AND expiration = :exp"
        params["exp"] = expiration.isoformat()
    sql = f"""
        SELECT id, root, underlying_symbol, underlying_price, expiration, quote_time,
               multiplier, risk_free_rate, tick_size
        FROM option_chains
        {where}
        ORDER BY quote_time DESC
        LIMIT 1
    """
    with eng.begin() as conn:
        r = conn.execute(text(sql), params).fetchone()
        if not r:
            return None
        chain_id = r[0]
        contract_rows = conn.execute(text("""
            SELECT option_type, strike, bid, ask, last, iv, delta, gamma, theta, vega,
                   volume, open_interest
            FROM option_contracts WHERE chain_id = :cid
        """), {"cid": chain_id}).fetchall()
    expiration_d = date.fromisoformat(r[4])
    quote_time = _ensure_aware(r[5])
    underlying_price = float(r[3])
    underlying_symbol = r[2]
    multiplier = float(r[6])
    risk_free_rate = float(r[7] or 0.05)
    tick_size = float(r[8] or 0.01)

    contracts: list[OptionContract] = []
    for cr in contract_rows:
        try:
            contracts.append(OptionContract(
                root=root,
                underlying_symbol=underlying_symbol,
                underlying_price=underlying_price,
                option_type=OptionType(cr[0]),
                strike=float(cr[1]),
                expiration=expiration_d,
                multiplier=multiplier,
                bid=float(cr[2]),
                ask=float(cr[3]),
                last=float(cr[4]) if cr[4] is not None else None,
                iv=float(cr[5]),
                delta=float(cr[6]),
                gamma=float(cr[7]),
                theta=float(cr[8]),
                vega=float(cr[9]),
                volume=int(cr[10] or 0),
                open_interest=int(cr[11] or 0),
                quote_time=quote_time,
                risk_free_rate=risk_free_rate,
                tick_size=tick_size,
            ))
        except Exception:
            continue
    return OptionChain(
        root=root,
        underlying_symbol=underlying_symbol,
        underlying_price=underlying_price,
        expiration=expiration_d,
        quote_time=quote_time,
        contracts=contracts,
        multiplier=multiplier,
    )


# ---------------------------------------------------------------------------
# Data warehouse — ingest audit
# ---------------------------------------------------------------------------
def start_ingest_run(vendor: str) -> int:
    eng = make_engine()
    with eng.begin() as conn:
        res = conn.execute(text("""
            INSERT INTO ingest_runs (vendor, started_at, status)
            VALUES (:vendor, :started_at, 'running')
        """), {"vendor": vendor, "started_at": datetime.utcnow()})
        return int(res.lastrowid)


def finish_ingest_run(run_id: int, *, rows_added: int, status: str = "success",
                      error_message: str | None = None) -> None:
    eng = make_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE ingest_runs
               SET completed_at = :ca, rows_added = :ra, status = :s, error_message = :em
             WHERE id = :id
        """), {"id": run_id, "ca": datetime.utcnow(), "ra": rows_added,
                "s": status, "em": error_message})


def ingest_status() -> list[dict]:
    """Last ingest per vendor + total row counts in each warehouse table."""
    eng = make_engine()
    with eng.begin() as conn:
        last_per_vendor = conn.execute(text("""
            SELECT vendor, MAX(completed_at) AS last_ok,
                   SUM(CASE WHEN status='success' THEN rows_added ELSE 0 END) AS total_ok,
                   COUNT(*) AS runs
            FROM ingest_runs GROUP BY vendor
        """)).fetchall()
        h_count = conn.execute(text("SELECT COUNT(*) FROM headlines")).scalar() or 0
        s_count = conn.execute(text("SELECT COUNT(*) FROM macro_signals")).scalar() or 0
        c_count = conn.execute(text("SELECT COUNT(*) FROM option_chains")).scalar() or 0
    return [
        {"per_vendor": [
            {"vendor": r[0], "last_ok": r[1], "total_rows_ok": r[2], "runs": r[3]}
            for r in last_per_vendor
        ]},
        {"warehouse_counts": {
            "headlines": h_count,
            "macro_signals": s_count,
            "option_chains": c_count,
        }},
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ensure_aware(d: datetime) -> datetime:
    """SQLite returns naive datetimes; pin to UTC."""
    if d is None:
        return d
    if isinstance(d, str):
        # ISO string fallback
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(tz=timezone.utc)
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


_TITLE_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_title(t: str) -> str:
    t = unicodedata.normalize("NFKC", t).lower()
    return re.sub(r"\s+", " ", _TITLE_NORM_RE.sub(" ", t)).strip()
