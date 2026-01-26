# 📌 ScoopzTool - Quick Reference

## 🚀 Bắt Đầu Nhanh

### 1. Chạy Tool

```powershell
# Windows
.\dist\ScoopzTool.exe

# Hoặc từ source code
python gui_app.py
```

### 2. Kiểm Tra Upload Status

```powershell
# Tóm tắt tất cả emails
powershell -ExecutionPolicy Bypass -File check_upload_status.ps1 -Summary

# Chi tiết từng email
powershell -ExecutionPolicy Bypass -File check_upload_status.ps1 -Details
```

### 3. Xem CSV File Upload Details

- Mở: `video/[email]/shorts.csv` bằng Excel
- Xem cột `status`:
  - `true` = Uploaded ✅
  - `false` = Not uploaded ❌

---

## 📁 Cấu Trúc Dữ Liệu

```
tool_rewrite/
├── dist/ScoopzTool.exe              ← Chạy tool (exe build)
├── gui_app.py                       ← Main GUI
├── video/                           ← Quản lý video từng email
│   ├── abodmotsis_at_hotmail_com/
│   │   └── shorts.csv              ← 5,660 videos
│   ├── adlaheok_at_hotmail_com/
│   │   └── shorts.csv              ← 23 videos
│   └── ... (192 emails total)
├── cookies.txt                      ← YouTube session (copy để dùng máy khác)
├── logs/                            ← Upload logs
├── accounts_cache.json              ← Account credentials
├── profile_accounts_cache.json      ← Profile data
├── USAGE_GUIDE.md                   ← Full documentation
└── check_upload_status.ps1          ← Check upload status script
```

---

## 📊 Upload Status Stats

```
Total: 192 emails
Uploaded: 4,826 videos (✅ 2.4%)
Failed: 197,011 videos (❌ 97.6%)
```

**Top Remaining (need to upload):**

- koraaadaeze_at_hotmail_com: 9,989 videos
- ribadalapiza_at_hotmail_com: 9,785 videos
- caletserab15_at_hotmail_com: 4,509 videos

---

## 🍪 Cookie Management

### Sử Dụng Cookies

**Trên máy cùng:**

- Tool tự động dùng file `cookies.txt`
- Không cần config gì

**Trên máy khác:**

```powershell
# Copy file từ máy cũ
Copy-Item "cookies.txt" -Destination "C:\new_machine\tool_rewrite\"

# Hoặc delete để generate cookie mới
Remove-Item "cookies.txt"
# Chạy tool - nó sẽ tạo cookie mới cho IP máy này
```

### Tại Sao Không Bị Trùng?

- Cookie = YouTube session (IP-based)
- Mỗi máy = 1 IP = 1 session cookie
- Không conflict giữa các máy

---

## 📝 CSV File Format

```csv
video_id,title,url,status
keSB3SS4Vro,Why are guys...,https://www.youtube.com/shorts/keSB3SS4Vro,true
d53w6sc-7Ko,Do you feel...,https://www.youtube.com/shorts/d53w6sc-7Ko,true
oD1x982lMD4,,https://www.youtube.com/shorts/oD1x982lMD4,false
```

**Cột:**

- `video_id`: YouTube short ID
- `title`: Video title (empty if not downloaded)
- `url`: YouTube URL
- `status`: `true` = uploaded, `false` = pending

---

## 🎯 Workflow

### 1. Upload Mode (Recommended)

```
1. Tool reads video/[email]/shorts.csv
2. Finds all videos with status=false
3. Downloads from YouTube (if needed)
4. Uploads to Scoopz
5. Updates status=true in CSV
6. Repeats for next email
```

### 2. Join Circles Mode

```
1. Creates GPM profile for each account
2. Logs in to Scoopz
3. Goes to https://thescoopz.com/circles
4. Scrolls to load circles
5. Joins random circles (up to max count)
6. Updates status in GUI
```

### 3. Interact Mode

```
1. Reads URL list from text area
2. For each URL:
   - Watches for N seconds (random)
   - Likes video (random)
   - Comments (if enabled)
   - Follows channel
3. Updates progress in real-time
```

---

## 🔍 Checking Upload Success

### Method 1: PowerShell Script

```powershell
powershell -ExecutionPolicy Bypass -File check_upload_status.ps1 -Summary
```

### Method 2: Manual Check

```powershell
# Open specific email's CSV
Start-Process "video\abodmotsis_at_hotmail_com\shorts.csv"

# Count uploaded
[array]$csv = Import-Csv "video\abodmotsis_at_hotmail_com\shorts.csv"
($csv | Where status -eq true).Count
```

### Method 3: Check Logs

```powershell
# View upload logs
Get-Content "logs\*.log" | tail -50
```

---

## 🛠️ Troubleshooting

### Issue: Videos uploaded to wrong circle?

- Check `CIRCLE_SELECTION_GUIDE.md` for keywords
- Manually set circle in form (dropdown selection)

### Issue: Upload fails with rate limit?

- Delete `cookies.txt`
- Wait 1-2 hours
- Run tool again (new cookie generated)

### Issue: CSV shows wrong status?

- Open file in Excel
- Make sure encoding is UTF-8
- Save and refresh tool

### Issue: Tool won't start?

- Check Python version: `python --version` (need 3.10+)
- Reinstall requirements: `pip install -r requirements.txt`

---

## 📞 Quick Commands

```powershell
# Check upload progress
powershell -ExecutionPolicy Bypass -File check_upload_status.ps1 -Summary

# View specific email status
powershell -ExecutionPolicy Bypass -File check_upload_status.ps1 -Details | grep "email_name"

# Open tool
.\dist\ScoopzTool.exe

# Run from source
python gui_app.py

# View latest logs
Get-Content "logs\*.log" -Tail 50
```

---

## 📚 Full Documentation

See `USAGE_GUIDE.md` for detailed documentation on:

- Folder structure and purpose
- CSV file format and tracking
- Cookie management for multi-machine
- Circle keyword matching
- Account setup and profiles

---

**Last Updated:** 2026-01-24  
**Version:** 1.0 with GUI, Circle Selection, Smart Interactions
