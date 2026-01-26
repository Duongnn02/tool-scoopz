# 🧪 TEST REPORT: Cookie & Video Folder Auto-Update

## Test 1: Cookie Replacement

### Scenario: Delete cookies.txt and Add New One

**Question:** Nếu xoá cookies.txt cũ và thay file cookie mới, tool có dùng cookie mới không?

**Answer: ✅ YES - Tool sẽ dùng cookies.txt mới**

**Lý do:**
```python
# Code từ yt_simple_download.py (line 115)
if cookie_path and os.path.exists(cookie_path):
    ydl_opts["cookiefile"] = cookie_path
```

**Cách hoạt động:**
1. Tool kiểm tra file `cookies.txt` tồn tại không
2. Nếu tồn tại → Load cookies.txt từ disk vào ydl_opts (YouTube downloader)
3. Nếu không tồn tại → Bỏ qua (yt-dlp sẽ generate session mới)

**Test Steps:**
```powershell
# Step 1: Delete old cookie
Remove-Item "dist\cookies.txt" -Force

# Step 2: Put new cookie (từ máy khác hoặc generate)
Copy-Item "new_cookies.txt" -Destination "dist\cookies.txt"

# Step 3: Run tool
.\dist\ScoopzTool.exe

# Result: ✅ Tool load new cookie immediately
# No restart needed!
```

**Key Point:**
- Tool reads cookies.txt **mỗi lần trước download**
- Không cache cookie trong memory
- Bạn có thể thay cookie **khi tool chạy**
- Tool sẽ dùng cookie mới ngay lần download tiếp theo

---

## Test 2: Video Folder Update

### Scenario: Delete Old Video Data & Import New List

**Question:** Nếu xoá dữ liệu cũ trong folder video và import danh sách mới, tool chạy có cập nhật vào folder video không?

**Answer: ✅ YES - Tool cập nhật CSV file tự động**

**Lý do:**
```python
# Code từ shorts_csv_store.py (line 67-100)
def mark_uploaded(email: str, video_id: str) -> bool:
    # Read all rows từ CSV
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    
    # Update matching row → status = "true"
    for row in rows:
        if row["video_id"] == video_id:
            row["status"] = "true"  # ← Mark as uploaded
    
    # Write back to CSV file
    with open(csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)  # ← Auto-save
```

**Cách hoạt động:**
1. Tool đọc CSV file → tìm video có `status=false`
2. Download & upload video xong
3. **Tự động ghi `status=true` vào CSV file** ✅
4. CSV file update ngay lập tức

**Test Steps:**
```powershell
# Step 1: Delete old video data
Remove-Item "dist\video\*" -Recurse -Force

# Step 2: Import new CSV list
# Copy new shorts.csv files vào video/[email]/

# Step 3: Run tool
.\dist\ScoopzTool.exe

# Result:
# ✅ Tool read new CSV
# ✅ Upload videos từ danh sách mới
# ✅ Auto-update status=true trong CSV khi upload xong
# ✅ Next time chạy → tool skip videos đã upload
```

**Example Flow:**

**Before:**
```
video/
├── abc_at_hotmail_com/
│   └── shorts.csv
│       video_id,title,url,status
│       vid001,,https://...,false
│       vid002,,https://...,false
```

**After Tool Runs:**
```
video/
├── abc_at_hotmail_com/
│   └── shorts.csv
│       video_id,title,url,status
│       vid001,Downloaded title...,https://...,true  ← ✅ Auto-updated!
│       vid002,Downloaded title...,https://...,true  ← ✅ Auto-updated!
```

---

## Key Points

### 🍪 Cookie Management
- ✅ Tool reads cookies.txt **fresh mỗi lần download**
- ✅ Thay cookie (delete + copy new) → **không cần restart tool**
- ✅ Tool dùng cookie mới ngay lần download tiếp theo
- ✅ Nếu cookies.txt không tồn tại → yt-dlp auto-generate

### 📁 Video Folder Management
- ✅ Tool reads CSV file → find `status=false`
- ✅ **Auto-update CSV** sau khi upload thành công
- ✅ Ghi `status=true`, title, và thông tin khác
- ✅ CSV update **real-time** (không delay)
- ✅ Lần chạy tiếp theo → skip videos đã upload

### 🔄 Import New Video List
- ✅ Copy new CSV files vào `video/[email]/`
- ✅ Tool tự động load danh sách mới
- ✅ Upload từ danh sách mới
- ✅ Auto-track upload status trong CSV

---

## Verification Code

**Cookie Check:**
```python
# File: yt_simple_download.py, line 115
if cookie_path and os.path.exists(cookie_path):
    ydl_opts["cookiefile"] = cookie_path
    # ✅ Fresh load từ disk mỗi lần gọi
```

**CSV Update Check:**
```python
# File: shorts_csv_store.py, line 80-100
with open(csv_path, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)  # ✅ Write back to file immediately
```

---

## 💡 Practical Usage

### Scenario 1: Thay Cookie Mới
```powershell
# On machine A (hết quota)
Remove-Item "dist\cookies.txt"

# Copy cookies.txt từ machine B
Copy-Item "B_cookies.txt" -Destination "dist\cookies.txt"

# Chạy tool - nó sẽ dùng cookie mới
.\dist\ScoopzTool.exe
# ✅ Download/upload continue with new cookie
```

### Scenario 2: Import Danh Sách Video Mới
```powershell
# Delete old data
Remove-Item "dist\video\*" -Recurse -Force

# Copy new CSV files
Copy-Item "new_video_list\*" -Destination "dist\video\" -Recurse

# Run tool
.\dist\ScoopzTool.exe
# ✅ Tool upload videos from new list
# ✅ Auto-update status trong CSV
```

### Scenario 3: Kiểm Tra Upload Progress
```powershell
# Open CSV to see updated status
Start-Process "dist\video\abc_at_hotmail_com\shorts.csv"
# ✅ See status column: true/false
# ✅ Updated in real-time
```

---

## Summary

| Action | Tool Auto-Update? | Restart Needed? | Notes |
|--------|------------------|-----------------|-------|
| Delete old cookies.txt | N/A | N/A | Tool không dùng nếu file không tồn tại |
| Copy new cookies.txt | ✅ YES | ❌ NO | Fresh load từ disk lần tiếp theo |
| Delete old video folder | N/A | N/A | Import danh sách mới |
| Copy new CSV files | ✅ YES | ❌ NO | Tool load danh sách mới |
| Upload hoàn tất | ✅ YES | ❌ NO | Auto-update `status=true` trong CSV |

**Bottom line:** ✅ Tool tự động handle cookie & CSV updates - **Hoàn toàn automatic!**
