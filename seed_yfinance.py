#!/usr/bin/env python3
"""
Seed Postgres with closing option chain data from yfinance.
Runs standalone, no TWS needed.

Schema:
  option_chains:    id, root, underlying_symbol, underlying_price,
                    expiration, quote_time, multiplier, vendor, ingested_at
  option_contracts: id, chain_id, option_type, strike, bid, ask, last,
                    iv, delta, gamma, theta, vega, volume, open_interest
"""
import os
import sys
import logging
from datetime import datetime
import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_yfinance")

DB_URL = os.getenv("DATABASE_URL", "postgresql://marketdata:marketdata@timescaledb:5432/marketdata")
TICKERS = ["EEM", "SPY", "QQQ", "FXI", "IWM"]

def get_conn():
    return psycopg2.connect(DB_URL)

def upsert_chain(conn, ticker, underlying_price, expiry_str, contracts_df, option_type):
    if contracts_df is None or contracts_df.empty:
        return 0

    cur = conn.cursor()
    now = datetime.utcnow()

    # Insert parent chain row — one per (root, expiration, quote_time)
    cur.execute("""
        INSERT INTO option_chains
            (root, underlying_symbol, underlying_price, expiration,
             quote_time, multiplier, vendor, ingested_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (ticker, ticker, underlying_price, expiry_str, now, 100.0, 'yfinance', now))
    chain_id = cur.fetchone()[0]

    rows = []
    for _, row in contracts_df.iterrows():
        rows.append((
            chain_id,
            option_type,                              # 'C' or 'P'
            float(row.get("strike", 0) or 0),
            float(row.get("bid", 0) or 0),
            float(row.get("ask", 0) or 0),
            float(row.get("lastPrice", 0) or 0),
            float(row.get("impliedVolatility", 0) or 0),
            float(row.get("delta", 0) or 0),
            float(row.get("gamma", 0) or 0),
            float(row.get("theta", 0) or 0),
            float(row.get("vega", 0) or 0),
            int(v) if (v := float(row.get("volume", 0) or 0)) == v else 0,
            int(v) if (v := float(row.get("openInterest", 0) or 0)) == v else 0,
        ))

    execute_values(cur, """
        INSERT INTO option_contracts
            (chain_id, option_type, strike, bid, ask, last, iv,
             delta, gamma, theta, vega, volume, open_interest)
        VALUES %s
    """, rows)

    conn.commit()
    cur.close()
    return len(rows)

def seed_ticker(conn, ticker):
    log.info(f"=== {ticker} ===")
    t = yf.Ticker(ticker)

    # Get current/last price
    try:
        underlying_price = t.fast_info["lastPrice"]
    except Exception:
        underlying_price = 0.0

    expirations = t.options
    if not expirations:
        log.warning(f"{ticker}: no expirations found")
        return

    log.info(f"{ticker}: {len(expirations)} expirations, last price {underlying_price:.2f}")
    total = 0

    for expiry in expirations:
        try:
            chain = t.option_chain(expiry)
            n_calls = upsert_chain(conn, ticker, underlying_price, expiry, chain.calls, "C")
            n_puts  = upsert_chain(conn, ticker, underlying_price, expiry, chain.puts,  "P")
            log.info(f"  {expiry}: {n_calls} calls + {n_puts} puts")
            total += n_calls + n_puts
        except Exception as e:
            log.error(f"  {expiry}: {e}")
            conn.rollback()

    log.info(f"{ticker}: total {total} contracts loaded")

def main():
    tickers = sys.argv[1:] if len(sys.argv) > 1 else TICKERS
    conn = get_conn()
    for ticker in tickers:
        try:
            seed_ticker(conn, ticker)
        except Exception as e:
            log.error(f"{ticker} failed: {e}")
            conn.rollback()
    conn.close()

if __name__ == "__main__":
    main()
