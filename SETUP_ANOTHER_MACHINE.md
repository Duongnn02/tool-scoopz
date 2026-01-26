# 🔄 Hướng Dẫn Dùng Tool Trên Máy Khác

## 1. 📋 Chuẩn Bị Trên Máy Cũ

### Bước 1: Thu Gom Dữ Liệu Cần Copy

**Folder/File BẮT BUỘC copy:**
```
tool_rewrite/
├── dist/ScoopzTool.exe          ← EXE (hoặc source code)
├── gui_app.py
├── scoopz_uploader.py
├── scoopz_interaction.py
├── login_scoopz.py
├── ... (tất cả .py files)
├── video/                        ← QUAN TRỌNG (danh sách video từng email)
├── accounts_cache.json           ← Thông tin accounts
├── profile_accounts_cache.json
├── config.py
├── requirements.txt
└── cookies.txt                   ← QUAN TRỌNG (YouTube session)
```

**Folder/File KHÔNG cần copy:**
```
logs/                    ← Log files (old, không cần)
profile_images/         ← Profile pictures (auto download lại)
html_snapshots/         ← HTML caches (auto tạo lại)
__pycache__/           ← Python cache (auto tạo lại)
build/                 ← Build folder (không cần)
.venv/                 ← Python venv (tạo mới trên máy khác)
```

### Bước 2: Tạo Folder Zip (Optional)

```powershell
# Trên máy cũ: Zip toàn bộ folder
Compress-Archive -Path "tool_rewrite" -DestinationPath "tool_rewrite_backup.zip" -Force

# Copy zip sang máy mới
```

---

## 2. 🚀 Setup Trên Máy Mới

### Phương Án A: Copy Exe (DỄ NHẤT) ✅ Khuyến Nghị

**Bước 1: Copy folder tool_rewrite**
```powershell
# Copy từ USB/network
Copy-Item "D:\tool_rewrite" -Destination "C:\laragon\www\tool scoopz\" -Recurse

# Hoặc từ zip
Expand-Archive "tool_rewrite_backup.zip" -DestinationPath "C:\laragon\www\tool scoopz\"
```

**Bước 2: Kiểm tra file cần thiết**
```powershell
cd "C:\laragon\www\tool scoopz\tool_rewrite"

# Kiểm tra exe tồn tại
Test-Path "dist\ScoopzTool.exe"  # Should return TRUE

# Kiểm tra cookies
Test-Path "cookies.txt"  # Should return TRUE
```

**Bước 3: Chạy tool**
```powershell
.\dist\ScoopzTool.exe
```

**Lợi ích:**
- ✅ Không cần cài Python
- ✅ Không cần setup venv
- ✅ Dùng cookies.txt cũ (vẫn hợp lệ)
- ✅ Chạy ngay lập tức

---

### Phương Án B: Chạy Từ Source Code

**Bước 1: Copy toàn bộ folder**
```powershell
Copy-Item "tool_rewrite" -Destination "C:\laragon\www\tool scoopz\" -Recurse
```

**Bước 2: Cài Python (nếu chưa có)**
```powershell
# Kiểm tra Python
python --version  # Should be 3.10+

# Nếu không có, cài từ python.org hoặc use Laragon
```

**Bước 3: Tạo Virtual Environment**
```powershell
cd "C:\laragon\www\tool scoopz\tool_rewrite"

# Tạo venv mới
python -m venv .venv

# Activate venv
.\.venv\Scripts\Activate.ps1

# Cài requirements
pip install -r requirements.txt
```

**Bước 4: Chạy tool**
```powershell
python gui_app.py
```

---

## 3. 🍪 Cookie Management - Trường Hợp Khác Nhau

### Trường Hợp 1: Dùng Lần Đầu Trên Máy Mới (PHỔ BIẾN)

**Cookie cũ từ máy cũ còn hợp lệ không?**

```
YouTube Cookie Expiry = 30-90 ngày (tuỳ type)
Nếu copy ngay: ✅ Cookie vẫn dùng được
Nếu để lâu:    ❌ Cookie hết hạn → cần mới
```

**Cách làm:**

**Option A: Copy cookies.txt từ máy cũ** (Nếu <7 ngày)
```powershell
# Trên máy cũ
Copy-Item "cookies.txt" -Destination "C:\USB\backup\"

# Trên máy mới
Copy-Item "C:\USB\backup\cookies.txt" -Destination "C:\laragon\www\tool scoopz\tool_rewrite\"

# Chạy tool → nó dùng cookies cũ luôn
```

**Option B: Để tool generate cookie mới** (Nếu >7 ngày)
```powershell
# Trên máy mới: Xoá file cookies.txt cũ
Remove-Item "cookies.txt" -Force

# Chạy tool
.\dist\ScoopzTool.exe

# Tool tự động:
# 1. Detect không có cookies.txt
# 2. Download từ YouTube → generate cookie mới
# 3. Lưu vào cookies.txt
# 4. Dùng cookie mới này
```

---

### Trường Hợp 2: Chạy Trên Nhiều Máy Cùng Lúc (QUAN TRỌNG)

**Vấn đề có thể xảy ra:**
```
Máy A (IP 1) + Cookie cũ = OK ✅
Máy B (IP 2) + Cookie cũ = ❌ EXPIRED (vì IP khác)

YouTube phát hiện: "Cookie từ IP A, nhưng request từ IP B"
→ Cookie reject → Rate limit / Download fail
```

**Giải pháp:**

**✅ Cách Đúng (KHUYÊN DÙNG):**

```powershell
# Máy A: Dùng cookies.txt cũ
.\dist\ScoopzTool.exe  ← Dùng cookie từ IP A

# Máy B: Tạo cookie riêng
Remove-Item "cookies.txt" -Force
.\dist\ScoopzTool.exe  ← Tool tạo cookie mới cho IP B

# Kết quả:
# Máy A: 1 cookie (IP A)
# Máy B: 1 cookie riêng (IP B)
# → Không conflict!
```

**❌ KHÔNG NÊN LÀM:**
```
Copy cookies.txt từ Máy A → Máy B
Cả 2 máy dùng cùng 1 cookie
→ YouTube detect 1 cookie từ 2 IPs khác nhau
→ Block / Rate limit
```

---

### Trường Hợp 3: Máy Cũ Vẫn Dùng, Máy Mới Cũng Dùng

**Setup:**
```
Máy Cũ (IP 1): ← Cookie 1
Máy Mới (IP 2): ← Cookie 2 (generate riêng)
```

**Bước:**

```powershell
# Máy Cũ: Giữ nguyên
# (không cần làm gì)

# Máy Mới:
cd "C:\laragon\www\tool scoopz\tool_rewrite"
Remove-Item "cookies.txt"
.\dist\ScoopzTool.exe  # Generate cookie mới

# Tool sẽ:
# 1. Detect không có cookies.txt
# 2. Download từ YouTube
# 3. Tạo cookies.txt mới cho IP Máy Mới
# 4. Dùng cookie mới này
```

**Result:**
```
Máy A (192.168.1.100): uploads 100/ngày
Máy B (192.168.1.101): uploads 100/ngày
Tổng: 200/ngày (không conflict)
```

---

## 4. 🔄 Workflow Chi Tiết - Máy Mới

### Scenario: Copy Tool Từ Máy Cũ → Máy Mới

**Bước 1: Trên Máy Cũ**
```powershell
cd "C:\laragon\www\tool scoopz\tool_rewrite"

# Tạo backup
Compress-Archive -Path "." -DestinationPath "tool_backup.zip" -Force

# Copy qua USB/Network
Copy-Item "tool_backup.zip" "D:\USB\"
Copy-Item "cookies.txt" "D:\USB\"  # Optional, để dùng cookie cũ
```

**Bước 2: Trên Máy Mới**
```powershell
# Unzip
Expand-Archive "D:\USB\tool_backup.zip" -DestinationPath "C:\laragon\www\tool scoopz\tool_rewrite"

cd "C:\laragon\www\tool scoopz\tool_rewrite"

# Kiểm tra ScoopzTool.exe tồn tại
Test-Path "dist\ScoopzTool.exe"
```

**Bước 3: Cookie Strategy (Chọn 1)**

**A. Nếu copy cookies.txt từ Máy Cũ (máy cũ không dùng nữa):**
```powershell
# Máy cũ không hoạt động → Dùng cookie cũ an toàn
# Tool chạy ngay lập tức
.\dist\ScoopzTool.exe
```

**B. Nếu Máy Cũ vẫn hoạt động (KHUYÊN):**
```powershell
# Xoá cookies.txt cũ
Remove-Item "cookies.txt" -Force

# Chạy tool → nó generate cookie mới
.\dist\ScoopzTool.exe

# Tool tự động tạo cookies.txt mới cho Máy Mới
```

**Bước 4: Kiểm Tra Upload**
```powershell
# Check status
powershell -File check_upload_status.ps1 -Summary

# Hoặc mở CSV file
video/[email]/shorts.csv  # Xem status (true/false)
```

---

## 5. ⚠️ Troubleshooting - Cookie Issues

### Vấn Đề 1: "Download fails" / "Rate limited"

**Nguyên nhân:**
- Cookie expire
- Cookie từ IP khác
- YouTube block

**Fix:**
```powershell
# Bước 1: Xoá cookie cũ
Remove-Item "cookies.txt" -Force

# Bước 2: Đợi 1-2 giờ (rate limit reset)
Start-Sleep -Seconds 3600

# Bước 3: Chạy tool lại
.\dist\ScoopzTool.exe
# Tool generate cookie mới
```

### Vấn Đề 2: 2 Máy Upload Conflict

**Triệu chứng:**
```
Máy A: Upload OK
Máy B: Rate limited / Download fail
```

**Nguyên nhân:**
- Cả 2 dùng 1 cookies.txt → YouTube detect
- 1 IP dùng 2 session → Block

**Fix:**
```powershell
# Máy B: Generate cookie riêng
Remove-Item "cookies.txt"
.\dist\ScoopzTool.exe
```

### Vấn đề 3: CSV File Không Update

**Nguyên nhân:**
- File bị lock (Excel đang mở)
- Permission error

**Fix:**
```powershell
# Đóng Excel
# Kiểm tra permission
icacls "video\*\shorts.csv" /grant:r "%USERNAME%":F

# Chạy tool lại
.\dist\ScoopzTool.exe
```

---

## 6. 📝 Checklist - Setup Máy Mới

- [ ] Copy folder tool_rewrite từ máy cũ
- [ ] Verify file tồn tại:
  - [ ] dist/ScoopzTool.exe hoặc gui_app.py
  - [ ] video/ folder (192 emails)
  - [ ] config.py
  - [ ] accounts_cache.json
- [ ] Cookie decision:
  - [ ] Copy cookies.txt (nếu máy cũ không dùng)
  - [ ] Delete cookies.txt (nếu máy cũ vẫn dùng)
- [ ] Chạy tool:
  - [ ] `.\dist\ScoopzTool.exe` (nếu dùng exe)
  - [ ] `python gui_app.py` (nếu dùng source)
- [ ] Kiểm tra kết quả:
  - [ ] Tool start OK
  - [ ] Có log file trong logs/
  - [ ] Có cookies.txt tạo mới (nếu xoá)
- [ ] Test upload:
  - [ ] Chạy 1-2 video
  - [ ] Check CSV update status

---

## 7. 💡 Best Practices

| Tình Huống | Làm Gì |
|-----------|--------|
| Máy mới, máy cũ không dùng | Copy cookies.txt từ máy cũ |
| Máy mới, máy cũ vẫn dùng | Delete cookies.txt, generate mới |
| 3+ máy chạy | Mỗi máy xoá cookies.txt, generate riêng |
| Cookie expire | Delete + đợi 1-2h + generate mới |
| Rate limit | Delete + đợi 2-4h + generate mới |
| Nhiều account, 1 máy | Dùng 1 cookies.txt chung (normal) |
| Nhiều máy, 1 account | Mỗi máy cookie riêng (important!) |

---

## 🎯 TL;DR - Cách Nhanh Nhất

**Máy mới lần đầu:**

```powershell
# 1. Copy tool từ máy cũ
# 2. Xoá file cookies.txt
# 3. Chạy
.\dist\ScoopzTool.exe
# 4. Done! Tool generate cookie tự động
```

**2+ máy chạy song song:**

```powershell
# Mỗi máy:
Remove-Item "cookies.txt"
.\dist\ScoopzTool.exe
# Mỗi máy sẽ có cookie riêng → không conflict
```

---

**Điểm quan trọng nhất:**
- ✅ Copy exe + toàn bộ folder video → Chạy ngay
- ✅ Nếu máy khác có IP khác → Delete cookies.txt để generate mới
- ✅ Không copy cookies.txt khi 2+ máy dùng cùng lúc
- ✅ Tool tự động handle cookie → Không cần config thêm
