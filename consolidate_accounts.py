# -*- coding: utf-8 -*-
"""
Consolidate all YTB and FB accounts from all data sources into a single
pipe-separated file.

Format: email|password|token|profile_uuid
  - token = empty (Microsoft refresh tokens not stored in workspace files)

Sources:
  1. cache.db → 'accounts'       (YTB)
  2. cache.db → 'profile_accounts'
  3. cache.db → 'fb_accounts'    (FB)
  4. ScoopzSync/ytb.json         (YTB, authoritative)
  5. ScoopzSync/fb.json          (FB, authoritative)
"""

import sqlite3
import json
import os

# ── helpers ──────────────────────────────────────────────────────────────────

def load_cache_key(db_path: str, key: str) -> list:
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("SELECT data FROM cache WHERE key = ?", (key,))
        row = c.fetchone()
        conn.close()
        return json.loads(row["data"]) if row else []
    except Exception as e:
        print(f"  [WARN] load_cache_key({key}): {e}")
        return []


def load_json(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"  [WARN] load_json({path}): {e}")
        return []


def normalise(acc: dict) -> dict:
    """Return a minimal normalised dict keyed by lower-case email."""
    return {
        "email":      (acc.get("uid") or "").strip().lower(),
        "pass":       (acc.get("pass") or "").strip(),
        "profile_id": (acc.get("profile_id") or "").strip(),
        "youtube":    (acc.get("youtube") or "").strip(),
        "facebook":   (acc.get("facebook") or "").strip(),
        "proxy":      (acc.get("proxy") or "").strip(),
        "followers":  acc.get("followers"),
        "posts":      acc.get("posts"),
        "status":     (acc.get("status") or "").strip(),
    }


def merge_into(store: dict, records: list, label: str = ""):
    """Merge list of raw account dicts into store (keyed by email).
    Later calls win on a per-field basis (non-empty beats empty).
    """
    added = updated = 0
    for raw in records:
        n = normalise(raw)
        email = n["email"]
        if not email:
            continue
        if email not in store:
            store[email] = n
            added += 1
        else:
            existing = store[email]
            changed = False
            for field in n:
                if n[field] and not existing.get(field):
                    existing[field] = n[field]
                    changed = True
            if changed:
                updated += 1
    if label:
        print(f"  {label}: +{added} new, ~{updated} enriched")


# ── load all sources ─────────────────────────────────────────────────────────

print("Loading data sources …")

ytb_all: dict = {}  # email → account
fb_all: dict  = {}  # email → account

# 1. ScoopzSync (authoritative – load first, then let cache.db overwrite where richer)
merge_into(ytb_all, load_json("ScoopzSync/ytb.json"),  "ScoopzSync/ytb.json")
merge_into(fb_all,  load_json("ScoopzSync/fb.json"),   "ScoopzSync/fb.json")

# 2. cache.db  
for key, store in [
    ("accounts",        ytb_all),
    ("profile_accounts", ytb_all),
    ("fb_accounts",      fb_all),
]:
    merge_into(store, load_cache_key("cache.db", key), f"cache.db[{key}]")

# Accounts that have a facebook field but ended up in ytb_all → move to fb
promoted = []
for email, acc in list(ytb_all.items()):
    if acc.get("facebook") and not acc.get("youtube"):
        fb_all.setdefault(email, acc)
        promoted.append(email)
for e in promoted:
    del ytb_all[e]

print(f"\nTotal unique YTB accounts: {len(ytb_all)}")
print(f"Total unique FB  accounts: {len(fb_all)}")

# ── write output ─────────────────────────────────────────────────────────────

def write_pipe_file(path: str, store: dict):
    lines = []
    for acc in store.values():
        email    = acc["email"]
        password = acc["pass"]
        token    = ""                    # not stored in workspace
        uuid     = acc["profile_id"]
        lines.append(f"{email}|{password}|{token}|{uuid}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  Written {len(lines):>4} lines → {path}")


print("\nWriting output …")
write_pipe_file("ytb_accounts_all.txt", ytb_all)
write_pipe_file("fb_accounts_all.txt",  fb_all)

# ── also write a combined file ────────────────────────────────────────────────
combined = {**ytb_all, **{f"[FB]{e}": a for e, a in fb_all.items()}}
all_lines = []
for email, acc in ytb_all.items():
    all_lines.append(f"{acc['email']}|{acc['pass']}||{acc['profile_id']}|YTB")
for email, acc in fb_all.items():
    all_lines.append(f"{acc['email']}|{acc['pass']}||{acc['profile_id']}|FB")

with open("all_accounts_consolidated.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(all_lines))
print(f"  Written {len(all_lines):>4} lines → all_accounts_consolidated.txt")

print("\nDone.")
