import sqlite3, os, json

# Check cookies
for i in ['', '_2', '_3', '_4']:
    paths = [
        f'chrome_automation_user_data{i}/Default/Network/Cookies',
        f'chrome_automation_user_data{i}/Default/Cookies',
    ]
    for cookie_path in paths:
        if os.path.exists(cookie_path):
            try:
                conn = sqlite3.connect(cookie_path)
                c = conn.cursor()
                c.execute("SELECT host_key, name FROM cookies WHERE host_key LIKE '%live.com%' OR host_key LIKE '%microsoft.com%' LIMIT 10")
                rows = c.fetchall()
                if rows:
                    print(f"\n{cookie_path} - Microsoft cookies:")
                    for row in rows:
                        print(" ", row)
                else:
                    c.execute("SELECT COUNT(*) FROM cookies")
                    total = c.fetchone()[0]
                    print(f"{cookie_path}: total {total} cookies, 0 Microsoft")
                conn.close()
            except Exception as e:
                print(f"{cookie_path}: {e}")
        else:
            pass
print("Done")
