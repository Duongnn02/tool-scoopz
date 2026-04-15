import sqlite3, json, os

def inspect_db(db_path):
    print(f"\n=== {db_path} ===")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print("Tables:", tables)
    for t in tables:
        print(f"\n-- Table: {t} --")
        c.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in c.fetchall()]
        print("Columns:", cols)
        c.execute(f"SELECT COUNT(*) FROM {t}")
        print("Row count:", c.fetchone()[0])
        c.execute(f"SELECT * FROM {t} LIMIT 2")
        for row in c.fetchall():
            print(dict(row))
    conn.close()

inspect_db("cache.db")
