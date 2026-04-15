import sqlite3

try:
    conn = sqlite3.connect("chrome_automation_user_data/Default/Account Web Data")
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print("Tables:", tables)
    for t in tables:
        c.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in c.fetchall()]
        print(f"\n  {t}: {cols}")
        c.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  rows: {c.fetchone()[0]}")
    conn.close()
except Exception as e:
    print("Error:", e)
