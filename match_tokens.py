# -*- coding: utf-8 -*-
"""
Tìm các email trong all_tokens_merged.txt trùng với email trong
ytb_accounts_all.txt / fb_accounts_all.txt (từ tool).

Output: matched_tokens.txt  — dòng token đầy đủ của email trùng
"""

import os

TOKEN_FILE = "all_tokens_merged.txt"
YTB_FILE   = "ytb_accounts_all.txt"
FB_FILE    = "fb_accounts_all.txt"
OUT_FILE   = "matched_tokens.txt"

def load_emails(path):
    emails = set()
    if not os.path.exists(path):
        print(f"  [SKIP] Not found: {path}")
        return emails
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            email = line.split("|")[0].strip().lower()
            if email:
                emails.add(email)
    return emails

def load_token_lines(path):
    lines = {}   # email_lower -> full line
    if not os.path.exists(path):
        print(f"  [SKIP] Not found: {path}")
        return lines
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            email = line.split("|")[0].strip().lower()
            if email:
                lines[email] = line
    return lines

# Load
ytb_emails   = load_emails(YTB_FILE)
fb_emails    = load_emails(FB_FILE)
token_lines  = load_token_lines(TOKEN_FILE)

tool_emails = ytb_emails | fb_emails
print(f"YTB accounts : {len(ytb_emails)}")
print(f"FB  accounts : {len(fb_emails)}")
print(f"Tool total   : {len(tool_emails)} unique emails")
print(f"Token file   : {len(token_lines)} entries")

# Match
matched = []
for email, line in token_lines.items():
    if email in tool_emails:
        src = []
        if email in ytb_emails:
            src.append("YTB")
        if email in fb_emails:
            src.append("FB")
        matched.append((email, line, "+".join(src)))

print(f"\nMatched      : {len(matched)}")

# Write output — full token line only (no extra tag)
with open(OUT_FILE, "w", encoding="utf-8") as f:
    for email, line, src in matched:
        f.write(line + "\n")

print(f"Written → {OUT_FILE}")

# Also write a tagged version for reference
with open("matched_tokens_tagged.txt", "w", encoding="utf-8") as f:
    for email, line, src in matched:
        f.write(f"{line}  [{src}]\n")

print(f"Written → matched_tokens_tagged.txt  (with YTB/FB tag)")

# Show emails in tool but NOT in token file
not_found = tool_emails - set(token_lines.keys())
print(f"\nEmails in tool but missing from token file: {len(not_found)}")
if not_found:
    with open("missing_tokens.txt", "w", encoding="utf-8") as f:
        for e in sorted(not_found):
            src = []
            if e in ytb_emails: src.append("YTB")
            if e in fb_emails:  src.append("FB")
            f.write(f"{e}  [{'+'.join(src)}]\n")
    print(f"Written → missing_tokens.txt")
