# -*- coding: utf-8 -*-
"""
Full C: drive scan for files containing |M.C<digit> pattern (Microsoft tokens).
Excludes binary/irrelevant extensions and our own output files.
"""
import os, re

SKIP_EXTS = {
    ".exe",".dll",".sys",".pdb",".mui",".cat",".msi",".cab",
    ".png",".jpg",".jpeg",".gif",".bmp",".mp4",".mp3",".ico",
    ".lnk",".pyc",".pyo",".zip",".rar",".7z",".gz",".tar",
    ".pdf",".docx",".xlsx",".pptx",".db",".sqlite",".sqlite3",
    ".woff",".woff2",".ttf",".eot",".svg",".webp",".wav",
}

OWN_FILES = {
    "all_tokens_merged.txt",
    "matched_tokens.txt",
    "matched_tokens_tagged.txt",
    "merge_tokens.py",
    "match_tokens.py",
    "consolidate_accounts.py",
}

# Regex: email|anything|M.C<digit>
PATTERN = re.compile(rb'\|M\.C[0-9]')

found = []
scanned = 0
errors = 0

for root, dirs, files in os.walk("C:\\"):
    # Skip system/cache dirs
    dirs[:] = [d for d in dirs if d.lower() not in {
        "windows", "windowsapps", "$recycle.bin", "system volume information",
        "programdata", "$windows.~bt", "$windows.~ws", "recovery",
        "perflogs", "__pycache__", ".git", "node_modules",
    }]

    for fname in files:
        ext = os.path.splitext(fname)[1].lower()
        if ext in SKIP_EXTS:
            continue
        if fname in OWN_FILES:
            continue

        path = os.path.join(root, fname)
        try:
            size = os.path.getsize(path)
            if size < 50 or size > 100 * 1024 * 1024:
                continue
            scanned += 1
            with open(path, "rb") as f:
                chunk = f.read(5 * 1024 * 1024)  # read up to 5MB
            if PATTERN.search(chunk):
                found.append(path)
                print(f"  FOUND: {path}")
        except Exception:
            errors += 1

print(f"\nScanned: {scanned}  Errors: {errors}")
print(f"Found {len(found)} files:")
for f in found:
    print(f"  {f}")

# Save list
with open("scan_results.txt", "w", encoding="utf-8") as f:
    for path in found:
        f.write(path + "\n")
print("\nWritten → scan_results.txt")
