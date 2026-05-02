"""FRED ingest. Pulls recent observations for a curated series list.

Backfill: explicit `since` parameter pulls every observation from that date.
Default mode pulls the most recent observation per series.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from app.config import get_settings
from app.storage.repository import upsert_macro_signals

log = logging.getLogger(__name__)

VENDOR = "fred"

_SERIES: list[tuple[str, str, str]] = [
    ("DGS2", "2y Treasury yield", "percent"),
    ("DGS10", "10y Treasury yield", "percent"),
    ("DGS30", "30y Treasury yield", "percent"),
    ("DFF", "Effective Fed Funds Rate", "percent"),
    ("T10Y2Y", "10y-2y spread", "percent"),
    ("T10Y3M", "10y-3m spread", "percent"),
    ("DTWEXBGS", "Dollar index (broad)", "index"),
    ("VIXCLS", "VIX close", "index"),
]


def ingest(*, since: date | datetime | None = None, **_kwargs) -> int:
    s = get_settings()
    if not s.fred_api_key:
        log.info("FRED_API_KEY not set; skipping FRED ingest")
        return 0

    rows: list[dict] = []
    for series_id, label, units in _SERIES:
        rows.extend(_fetch_series(s.fred_api_key, series_id, label, units, since))
    return upsert_macro_signals(rows, vendor=VENDOR)


def _fetch_series(api_key: str, series_id: str, label: str, units: str,
                  since: date | datetime | None) -> list[dict]:
    params: dict[str, object] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    if since is not None:
        if isinstance(since, datetime):
            since = since.date()
        params["observation_start"] = since.isoformat()
        params["sort_order"] = "asc"
    else:
        params["sort_order"] = "desc"
        params["limit"] = 1
    try:
        with httpx.Client(timeout=15.0) as c:
            r = c.get("https://api.stlouisfed.org/fred/series/observations", params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        log.warning("FRED %s failed: %s", series_id, e)
        return []
    out: list[dict] = []
    for obs in data.get("observations", []):
        v = obs.get("value")
        if v in (None, "", "."):
            continue
        try:
            as_of = datetime.fromisoformat(obs["date"]).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        out.append({
            "series_id": series_id,
            "label": label,
            "value": float(v),
            "as_of": as_of,
            "units": units,
        })
    return out
