# -*- coding: utf-8 -*-
import os

WORKSPACE = "C:\\Users\\Admin\\Desktop\\tool_rewrite\\tool_rewrite"

YTB      = os.path.join(WORKSPACE, "ytb_accounts_all.txt")
FB       = os.path.join(WORKSPACE, "fb_accounts_all.txt")
TOKENS   = os.path.join(WORKSPACE, "all_tokens_merged.txt")
SCOOPZ_NO_TOKEN = os.path.join(WORKSPACE, "scoopz_chua_co_token.txt")

OUT1 = os.path.join(WORKSPACE, "file1_tool_co_token.txt")
OUT2 = os.path.join(WORKSPACE, "file2_ngoai_tool_khong_token.txt")
OUT3 = os.path.join(WORKSPACE, "file3_ngoai_tool_co_token.txt")

def load_emails(path):
    """Return dict: email_lower -> original_line"""
    d = {}
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if parts and "@" in parts[0]:
                d[parts[0].strip().lower()] = line
    return d

# Load sets
ytb_map   = load_emails(YTB)
fb_map    = load_emails(FB)
tool_map  = {**ytb_map, **fb_map}          # 472 unique

token_map = load_emails(TOKENS)            # 425 unique, all have M.C token

# Load no-token list (from scoopz scan)
no_token_map = load_emails(SCOOPZ_NO_TOKEN)  # 103

print(f"Tool emails   : {len(tool_map)}")
print(f"Token emails  : {len(token_map)}")
print(f"No-token list : {len(no_token_map)}")

# --- File 1: trong tool VA co token ---
file1 = [token_map[e] for e in tool_map if e in token_map]

# --- File 2: ngoai tool VA khong co token ---
file2 = [no_token_map[e] for e in no_token_map if e not in tool_map]

# --- File 3: ngoai tool VA co token ---
file3 = [token_map[e] for e in token_map if e not in tool_map]

def write_file(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

write_file(OUT1, file1)
write_file(OUT2, file2)
write_file(OUT3, file3)

print(f"\nFile 1 (tool + co token)      : {len(file1)}")
print(f"File 2 (ngoai tool + ko token): {len(file2)}")
print(f"File 3 (ngoai tool + co token): {len(file3)}")
