import re
import urllib.request

url = "https://socialblade.com/youtube/lists/top/100/views/people/US"

req = urllib.request.Request(url, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
})

with urllib.request.urlopen(req, timeout=15) as resp:
    html = resp.read().decode("utf-8", errors="ignore")

handles = re.findall(r'href="(/youtube/handle/[^"]+)"', html)
handles = list(dict.fromkeys(handles))  # dedup preserve order

print(f"Found: {len(handles)} handles")
for h in handles:
    print(h)

with open("socialblade_handles.txt", "w", encoding="utf-8") as f:
    for h in handles:
        f.write(h + "\n")
print("\nSaved to socialblade_handles.txt")
