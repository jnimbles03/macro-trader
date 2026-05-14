"""Macro tape query layer.

Reads from the warehouse `macro_signals` table by default. `live=True`
bypasses and pulls from FRED directly (and persists to the warehouse).

Mock mode reads `fixtures/fred_snapshot.json`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.data.cache import cache_key, cached_call
from app.storage.repository import latest_macro_signals

log = logging.getLogger(__name__)


def get_market_tape(*, fresh: bool = False, live: bool = False) -> dict[str, Any]:
    s = get_settings()
    key = cache_key("market_tape", "live" if live else "warehouse",
                    "mock" if s.mock_data else "real")
    return cached_call(
        key,
        ttl_seconds=s.cache_regime_min * 60,
        fresh=fresh,
        loader=lambda: _load(s, live=live),
    )


def _load(s, *, live: bool) -> dict[str, Any]:
    if s.mock_data:
        return _load_fixture()

    if live:
        return _load_live()

    rows = latest_macro_signals()
    return {
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "signals": [
            {
                "series_id": r.series_id, "label": r.label, "value": r.value,
                "as_of": r.as_of.isoformat() if r.as_of else None,
                "units": r.units,
            }
            for r in rows
        ],
    }


def _load_live() -> dict[str, Any]:
    from app.ingest import fred
    from app.ingest.runner import run_one

    run_one("fred", fred.ingest)
    rows = latest_macro_signals()
    return {
        "as_of": datetime.now(tz=timezone.utc).isoformat(),
        "signals": [
            {
                "series_id": r.series_id, "label": r.label, "value": r.value,
                "as_of": r.as_of.isoformat() if r.as_of else None,
                "units": r.units,
            }
            for r in rows
        ],
    }


def _load_fixture() -> dict[str, Any]:
    s = get_settings()
    raw = json.loads((s.fixtures_dir / "fred_snapshot.json").read_text())
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
