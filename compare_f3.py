f3 = {l.split('|')[0].strip().lower() for l in open('file3_ngoai_tool_co_token.txt', encoding='utf-8', errors='ignore') if l.strip()}
con = {l.split('|')[0].strip().lower() for l in open('all_accounts_consolidated.txt', encoding='utf-8', errors='ignore') if l.strip()}
dup = sorted(f3 & con)
with open('compare_out.txt', 'w', encoding='utf-8') as o:
    o.write(f"file3: {len(f3)}\n")
    o.write(f"consolidated: {len(con)}\n")
    o.write(f"Trung: {len(dup)}\n")
    for e in dup:
        o.write(e + '\n')
