"""Macro tape: yields, spreads, DXY, VIX/MOVE.

Live mode pulls from FRED if a key is configured, otherwise returns the empty
tape (regime detector treats missing tape as low-confidence). Mock mode reads
`fixtures/fred_snapshot.json`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import get_settings
from app.data.cache import cache_key, cached_call

log = logging.getLogger(__name__)

# Series we care about for regime detection.
_FRED_SERIES: list[tuple[str, str, str]] = [
    ("DGS2", "2y Treasury yield", "percent"),
    ("DGS10", "10y Treasury yield", "percent"),
    ("DGS30", "30y Treasury yield", "percent"),
    ("DFF", "Effective Fed Funds Rate", "percent"),
    ("T10Y2Y", "10y-2y spread", "percent"),
    ("T10Y3M", "10y-3m spread", "percent"),
    ("DTWEXBGS", "Dollar index (broad)", "index"),
    ("VIXCLS", "VIX close", "index"),
]


def get_market_tape(*, fresh: bool = False) -> dict[str, Any]:
    s = get_settings()
    key = cache_key("market_tape", "mock" if s.mock_data else "live")
    return cached_call(
        key,
        ttl_seconds=s.cache_regime_min * 60,
        fresh=fresh,
        loader=lambda: _load(s),
    )


def _load(s) -> dict[str, Any]:
    if s.mock_data:
        return _load_fixture()
    if not s.fred_api_key:
        log.info("FRED_API_KEY not set; macro tape will be empty.")
        return {"as_of": datetime.now(tz=timezone.utc).isoformat(), "signals": []}
    return _fetch_fred(s.fred_api_key)


def _load_fixture() -> dict[str, Any]:
    s = get_settings()
    raw = json.loads((s.fixtures_dir / "fred_snapshot.json").read_text())
    # normalize fixture shape -> tape shape
    return {
        "as_of": raw.get("as_of"),
        "signals": [
            {
                "series_id": x["series_id"],
                "label": x["label"],
                "value": float(x["value"]),
                "as_of": x["as_of"],
                "units": x.get("units"),
            }
            for x in raw.get("series", [])
        ],
    }


def _fetch_fred(api_key: str) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=15.0) as c:
        for series_id, label, units in _FRED_SERIES:
            try:
                r = c.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": api_key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": 1,
                    },
                )
                r.raise_for_status()
                obs = r.json().get("observations", [])
                if not obs:
                    continue
                latest = obs[0]
                value = latest.get("value")
                if value in (None, "", "."):
                    continue
                out.append({
                    "series_id": series_id,
                    "label": label,
                    "value": float(value),
                    "as_of": latest.get("date"),
                    "units": units,
                })
            except Exception as e:
                log.warning("FRED %s failed: %s", series_id, e)
                continue
    return {"as_of": datetime.now(tz=timezone.utc).isoformat(), "signals": out}
