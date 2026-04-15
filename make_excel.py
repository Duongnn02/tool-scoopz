import openpyxl

WORKSPACE = "C:\\Users\\Admin\\Desktop\\tool_rewrite\\tool_rewrite"

file2_path  = WORKSPACE + "\\file2_ngoai_tool_khong_token.txt"
ytb_path    = WORKSPACE + "\\socialblade_ytb_links.txt"
out_path    = WORKSPACE + "\\result.xlsx"

# Load email|pass
rows_ep = []
with open(file2_path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        email = parts[0].strip() if len(parts) > 0 else ""
        pwd   = parts[1].strip() if len(parts) > 1 else ""
        rows_ep.append((email, pwd))

# Load ytb links
rows_ytb = []
with open(ytb_path, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        if line:
            rows_ytb.append(line)

total = max(len(rows_ep), len(rows_ytb))

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Data"

# Header
ws.append(["Email", "Password", "YTB Link"])

for i in range(total):
    email = rows_ep[i][0] if i < len(rows_ep) else ""
    pwd   = rows_ep[i][1] if i < len(rows_ep) else ""
    ytb   = rows_ytb[i]   if i < len(rows_ytb) else ""
    ws.append([email, pwd, ytb])

# Auto column width
for col in ws.columns:
    max_len = max(len(str(cell.value or "")) for cell in col)
    ws.column_dimensions[col[0].column_letter].width = min(max_len + 2, 80)

wb.save(out_path)
print(f"Saved: {out_path}")
print(f"Rows: {total} (email/pass: {len(rows_ep)}, ytb: {len(rows_ytb)})")
