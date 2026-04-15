# -*- coding: utf-8 -*-
"""
Fast scan for Microsoft token files. Skips large/binary dirs.
"""
import os, re

SKIP_DIRS = {
    "windows", "windowsapps", "$recycle.bin",
    "system volume information", "$windows.~bt", "$windows.~ws",
    "recovery", "perflogs", "programdata", "program files",
    "program files (x86)", "__pycache__", ".git", "node_modules",
    ".venv", "venv", "env", "site-packages",
    "appdata",  # contains huge browser caches
}

SKIP_EXTS = {
    ".exe",".dll",".sys",".pdb",".mui",".cat",".msi",".cab",
    ".png",".jpg",".jpeg",".gif",".bmp",".mp4",".mp3",".ico",
    ".lnk",".pyc",".pyo",".zip",".rar",".7z",".gz",".tar",
    ".pdf",".docx",".xlsx",".pptx",".db",".sqlite",".sqlite3",
    ".woff",".woff2",".ttf",".eot",".svg",".webp",".wav",".json",
}

OWN = {
    "all_tokens_merged.txt", "matched_tokens.txt",
    "matched_tokens_tagged.txt", "scan_results.txt",
    "merge_tokens.py", "match_tokens.py", "full_scan.py",
    "fast_scan.py","consolidate_accounts.py",
}

PATTERN = re.compile(rb'\|M\.C[0-9]')

found = []
scanned = 0

for root, dirs, files in os.walk("C:\\"):
    dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]

    for fname in files:
        if fname in OWN:
            continue
        ext = os.path.splitext(fname)[1].lower()
        if ext in SKIP_EXTS:
            continue

        path = os.path.join(root, fname)
        try:
            size = os.path.getsize(path)
            if size < 50 or size > 50 * 1024 * 1024:
                continue
            scanned += 1
            with open(path, "rb") as f:
                chunk = f.read(2 * 1024 * 1024)
            if PATTERN.search(chunk):
                found.append(path)
                print(f"FOUND: {path}")
        except Exception:
            pass

print(f"\nScanned {scanned} files, found {len(found)}")

with open("scan_results.txt", "w", encoding="utf-8") as f:
    for p in found:
        if p not in OWN:
            f.write(p + "\n")
print("Written → scan_results.txt")
