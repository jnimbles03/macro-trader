# Macro Options Scout

A local trading research agent. You "poke" it; it reads the last 24h of global
headlines, classifies macro channels, runs a persona-weighted lens pass, and
proposes **exactly two** options trade ideas:

1. **Trade 1** — defined-risk options spread with a hard `max_gain/max_loss ≥ 2.0` floor.
2. **Trade 2** — single long YOLO option on a futures contract.

Either slot can return **NO TRADE** if the signal is weak, conflicted, stale,
or not cleanly expressible in options.

## Critical constraints

- **Research only.** Never places live trades. Every output carries a
  "not financial advice — human review required" warning.
- **Never fabricates** prices, strikes, chains, Greeks, IV, headlines, or
  sources. Missing data ⇒ NO TRADE. There is no IV fallback from historical vol.
- **Naked short options are never permitted** in either slot.

## Dual-LLM synthesis

This build wires up:

- **Grok 4.1 Full** as the primary causal-engine / lens-pass / trade-selector LLM.
- **Claude Opus** as the validator. It receives Grok's output and is asked to
  challenge and fact-check four dimensions:
  1. **News** — are the cited headlines plausible / consistent with the corpus?
  2. **Trade theory** — is the causal chain coherent (rates ⇒ curve ⇒ vol ⇒ spread)?
  3. **Risk / reward** — does the spread truly clear `2.0`? Is the YOLO premium real?
  4. **Option strategy** — does the structure express the thesis cleanly, given
     liquidity, Greeks, and time horizon?

Opus's verdict is one of `accept`, `revise`, or `reject` per trade slot.
A `reject` flips the slot to NO TRADE with the validator's reason printed.

## Quick start

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env             # fill in keys, or keep MOCK_DATA=true
macro-scout config-check
MOCK_DATA=true macro-scout poke  # full deterministic end-to-end run
```

Run the local web UI:

```bash
uvicorn app.main:app --reload
```

## CLI

```
macro-scout poke
macro-scout poke --lookback 24h
macro-scout poke --market rates|equity|commodities|fx
macro-scout poke --risk-profile conservative|balanced|aggressive|yolo
macro-scout poke --fresh             # bypass in-process TTL cache
macro-scout poke --live              # bypass the warehouse, hit vendor APIs directly
macro-scout poke --dry-run
macro-scout headlines
macro-scout paper-log
macro-scout backtest-signals
macro-scout config-check
macro-scout data-status              # last ingest per vendor + warehouse counts
macro-scout ingest-all               # run every ingest job (cron / launchd target)
macro-scout ingest-headlines [--from YYYY-MM-DD] [--to YYYY-MM-DD]
macro-scout ingest-fred       [--from YYYY-MM-DD]
macro-scout ingest-chains     --roots ZN,ES [--expiration YYYY-MM-DD]
```

## Data warehouse

The bot is split into a write-side **ingest layer** and a read-side **query
layer**, both backed by the SQLite DB at `./data/macro_scout.db`.

```
ingest jobs            warehouse                      trading bots
─────────────          ─────────                      ────────────
GDELT     ─┐                                          ┌─ macro-scout poke
NewsAPI   ─┼─► headlines       ──┐                    │
RSS       ─┘                     │                    │
FRED      ──► macro_signals      ├─► reads ──────────►┤  (your next bot)
IBKR      ──► option_chains    ──┘                    │
              + option_contracts                      └─ ...
```

Schedule the ingest jobs externally so the warehouse stays warm:

```bash
./scripts/install-launchd.sh    # macOS launchd, runs ingest-all every 15 min
./scripts/uninstall-launchd.sh
```

Trading bots query the warehouse without hitting any vendor APIs themselves.
`--live` on a `poke` skips the warehouse and pulls fresh from vendors —
useful if you can't wait for the next cron tick.

Backfill: `ingest-headlines --from 2026-04-01` chunks the window into 24h
slices and pulls everything within. FRED ingest with `--from` does the same
on a per-series basis.

Adding a new vendor = drop a new file under `app/ingest/`, register it in
`runner.run_all`. Each vendor module exposes a single
`def ingest(*, since=None, lookback_hours=24, **kwargs) -> int` that returns
rows-added.

## Mock mode

`MOCK_DATA=true` runs the full pipeline against `fixtures/` with zero network
calls. Combined with `PAPER_MODE=true` the output is deterministic — same
fixtures in, same brief out. The test suite runs against these fixtures.

## Tests

```bash
pytest -q
```

## Disclaimer

Research artifact. Not financial advice. Human review required before any
order is placed by a human in any venue.
