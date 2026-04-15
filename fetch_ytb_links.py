import re
import time
import urllib.request

BASE = "https://socialblade.com"
HANDLES_FILE = "socialblade_handles.txt"
OUTPUT_FILE  = "socialblade_ytb_links.txt"
FAILED_FILE  = "socialblade_failed.txt"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

handles = [l.strip() for l in open(HANDLES_FILE, encoding="utf-8") if l.strip()]
print(f"Total handles: {len(handles)}")

results = []
failed  = []

for i, handle in enumerate(handles, 1):
    url = BASE + handle
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        # Extract YouTube channel link from "View on YouTube" button
        match = re.search(r'href="(https://www\.youtube\.com/channel/[^"]+)"', html)
        if match:
            yt_link = match.group(1)
            results.append(f"{handle}\t{yt_link}")
            print(f"[{i:3d}] OK  {handle} -> {yt_link}")
        else:
            failed.append(handle)
            print(f"[{i:3d}] MISS {handle}")
    except Exception as e:
        failed.append(handle)
        print(f"[{i:3d}] ERR  {handle} : {e}")

    time.sleep(0.8)  # polite delay

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for line in results:
        f.write(line + "\n")

with open(FAILED_FILE, "w", encoding="utf-8") as f:
    for line in failed:
        f.write(line + "\n")

print(f"\nDone: {len(results)} found, {len(failed)} failed")
print(f"Saved to {OUTPUT_FILE}")
