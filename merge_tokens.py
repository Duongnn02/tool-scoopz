# -*- coding: utf-8 -*-
"""
Merge all found token files into one deduplicated file.
Format per line: email|password|token|uuid
Dedup key: email (case-insensitive).
"""

import os

FILES = [
    r"C:\Users\Admin\Desktop\REG_SCOOPZ\REG_SCOOPZ\HOTMAIL.txt",
    r"C:\Users\Admin\Desktop\REG_SCOOPZ\REG_SCOOPZ\mail chuan.txt",
    r"C:\Users\Admin\Documents\mail kênh v2.txt",
    r"C:\Users\Admin\Downloads\mail goc.txt",
    r"C:\laragon\www\bot trade\data.txt",
]

OUT = r"C:\Users\Admin\Desktop\tool_rewrite\tool_rewrite\all_tokens_merged.txt"

seen = {}   # email_lower -> line (first occurrence wins)
raw_totals = {}

for path in FILES:
    count = 0
    skipped = 0
    if not os.path.exists(path):
        print(f"  [SKIP] Not found: {path}")
        continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            count += 1
            parts = line.split("|")
            if len(parts) < 2:
                skipped += 1
                continue
            email_key = parts[0].strip().lower()
            if email_key not in seen:
                seen[email_key] = line
            # else: keep first occurrence
    raw_totals[path] = (count, skipped)
    print(f"  {os.path.basename(path)}: {count} lines ({skipped} invalid)")

print(f"\nTotal unique (by email): {len(seen)}")

with open(OUT, "w", encoding="utf-8") as f:
    for line in seen.values():
        f.write(line + "\n")

print(f"Written → {OUT}")

# Stats breakdown
with open(OUT, "r", encoding="utf-8") as f:
    all_lines = [l.strip() for l in f if l.strip()]
has_token = sum(1 for l in all_lines if len(l.split("|")) >= 3 and l.split("|")[2].startswith("M.C"))
no_token  = len(all_lines) - has_token
print(f"\nWith Microsoft token: {has_token}")
print(f"Without token:        {no_token}")
