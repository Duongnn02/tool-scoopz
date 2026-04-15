import json
import requests
import csv

# 1. Fetch bank list from API
response = requests.get("https://api.banklookup.net/bank/list")
response.raise_for_status()
bank_data = response.json().get("data", [])

# Build a dict: bin (as string) -> short_name
bin_to_short_name = {}
for bank in bank_data:
    bin_val = str(bank.get("bin", "")).strip()
    short_name = bank.get("short_name", "")
    if bin_val:
        bin_to_short_name[bin_val] = short_name

print(f"Loaded {len(bin_to_short_name)} banks from API")

# 2. Load list_b2nks.json
with open("list_b2nks.json", encoding="utf-8") as f:
    records = json.load(f)

print(f"Loaded {len(records)} records from list_b2nks.json")

# 3. Map and build output
output = []
not_found = set()

for i, record in enumerate(records, start=1):
    n2ng_h2ng = str(record.get("n2ng_h2ng", "")).strip()
    short_name = bin_to_short_name.get(n2ng_h2ng, "")
    if not short_name:
        not_found.add(n2ng_h2ng)

    output.append({
        "stt": i,
        "name": record.get("name", ""),
        "stk": record.get("stk", ""),
        "bank": short_name
    })

if not_found:
    print(f"Warning: {len(not_found)} bin codes not found in API: {not_found}")

# 4. Deduplicate by stk (keep first occurrence)
seen_stk = set()
deduped = []
dup_count = 0
for row in output:
    stk = str(row["stk"]).strip()
    if stk in seen_stk:
        dup_count += 1
        continue
    seen_stk.add(stk)
    deduped.append(row)

# Re-number stt after dedup
for i, row in enumerate(deduped, start=1):
    row["stt"] = i

print(f"Removed {dup_count} duplicate stk entries. Remaining: {len(deduped)}")

# 5. Write to new CSV file
output_file = "output_banks.csv"
with open(output_file, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=["stt", "name", "stk", "bank"],
                            quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=False)
    writer.writeheader()
    writer.writerows(deduped)

print(f"Done! Saved {len(deduped)} rows to {output_file}")
