# -*- coding: utf-8 -*-
"""
So sanh tat ca email tu scoopz voi all_tokens_merged.txt
Output:
  scoopz_da_co_token.txt  -- email da co trong merged (trung)
  scoopz_chua_co_token.txt -- email chua co trong merged (moi)
"""
import os
import glob

SCOOPZ_DIR = "C:\\Users\\Admin\\Documents\\scoopz"
MERGED     = "C:\\Users\\Admin\\Desktop\\tool_rewrite\\tool_rewrite\\all_tokens_merged.txt"
OUT_HAVE   = "C:\\Users\\Admin\\Desktop\\tool_rewrite\\tool_rewrite\\scoopz_da_co_token.txt"
OUT_NEW    = "C:\\Users\\Admin\\Desktop\\tool_rewrite\\tool_rewrite\\scoopz_chua_co_token.txt"

# Bỏ qua file không liên quan
SKIP_FILES = {"tt bank.txt"}

# Load token map: email_lower -> full line (from merged)
token_map = {}
with open(MERGED, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if parts:
            token_map[parts[0].strip().lower()] = line

print(f"Token map loaded: {len(token_map)} entries\n")

# Đọc tất cả .txt từ scoopz
have_token   = []  # (email, original_line, source_file, token_line)
no_token     = []  # (email, original_line, source_file)
seen_emails  = set()

txt_files = glob.glob(os.path.join(SCOOPZ_DIR, "*.txt"))

for fpath in sorted(txt_files):
    fname = os.path.basename(fpath)
    if fname in SKIP_FILES:
        print(f"  [SKIP] {fname}")
        continue

    count_have = 0
    count_new  = 0
    count_skip = 0

    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            parts = raw.split("|")
            if len(parts) < 2:
                count_skip += 1
                continue
            email = parts[0].strip().lower()
            if not email or "@" not in email:
                count_skip += 1
                continue

            # Dedup across files
            if email in seen_emails:
                continue
            seen_emails.add(email)

            if email in token_map:
                have_token.append(token_map[email])   # dùng line đầy đủ có token
                count_have += 1
            else:
                no_token.append(raw)   # giữ nguyên line gốc
                count_new += 1

    print(f"  {fname}: {count_have} trung / {count_new} moi / {count_skip} bo qua")

# Ghi output
with open(OUT_HAVE, "w", encoding="utf-8") as f:
    f.write("\n".join(have_token) + "\n")

with open(OUT_NEW, "w", encoding="utf-8") as f:
    f.write("\n".join(no_token) + "\n")

print(f"\nTong trung (da co token): {len(have_token)}")
print(f"Tong moi (chua co token): {len(no_token)}")
print(f"\nOutput:")
print(f"  {OUT_HAVE}")
print(f"  {OUT_NEW}")
