"""Ingest layer.

Each vendor module exposes:

    def ingest(*, since: datetime | None = None,
               lookback_hours: int = 24,
               **kwargs) -> int

returning the number of rows inserted. The `runner` module orchestrates
all jobs and writes audit entries to `ingest_runs`.

This is the write-side of the data warehouse. Trading bots query the
`headlines` / `macro_signals` / `option_chains` tables via
`app.storage.repository`; they don't touch vendor APIs directly anymore.
"""
