import os
import sys
sys.path.insert(0, '/app')

db_url = os.getenv("DB_URL", "NOT SET")
print(f"DB_URL: {db_url}")

try:
    import psycopg2
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM option_contracts")
    print(f"option_contracts rows: {cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM option_chains")
    print(f"option_chains rows: {cur.fetchone()[0]}")
    conn.close()
    print("Postgres OK")
except Exception as e:
    print(f"Postgres ERROR: {e}")

try:
    from app.storage.db import _engine_url, make_engine
    url = _engine_url()
    print(f"SQLAlchemy URL: {url}")
    engine = make_engine()
    with engine.connect() as c:
        from sqlalchemy import text
        r = c.execute(text("SELECT COUNT(*) FROM option_contracts"))
        print(f"SQLAlchemy count: {r.scalar()}")
except Exception as e:
    print(f"SQLAlchemy ERROR: {e}")
