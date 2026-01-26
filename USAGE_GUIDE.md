# 📋 Hướng Dẫn Sử Dụng ScoopzTool

## 1. 📁 FOLDER VIDEO - Quản Lý Emails & Videos

### Cấu Trúc Thư Mục
```
video/
├── abodmotsis_at_hotmail_com/
│   └── shorts.csv          ← Danh sách video của email này
├── adlaheok_at_hotmail_com/
│   └── shorts.csv
├── agagabonces_at_hotmail_com/
│   └── shorts.csv
└── ... (201 emails tổng cộng)
```

### File `shorts.csv` - Chi Tiết Cấu Trúc

**Cột dữ liệu:**
```
video_id  | Title                                    | URL                           | Status
----------|------------------------------------------|-------------------------------|--------
keSB3SS4Vro | Why are guys so uncommunicative? | https://www.youtube.com/... | true
d53w6sc-7Ko | Do you feel it?🫰🏼🤣 #funny      | https://www.youtube.com/... | true
oD1x982lMD4 | (empty - chưa download)                | https://www.youtube.com/... | false
```

### Cột Status Là Gì?

| Status | Ý Nghĩa | Hành Động Cần Làm |
|--------|---------|-------------------|
| **true** | ✅ Video đã download & upload | Không cần làm gì |
| **false** | ❌ Video chưa download hoặc upload thất bại | Cần download/retry |

### Cách Kiểm Tra Upload

**Bước 1:** Mở file CSV của email bạn muốn kiểm tra
- Ví dụ: `video/abodmotsis_at_hotmail_com/shorts.csv`

**Bước 2:** Tìm video có `status=false`
```csv
oD1x982lMD4,,https://www.youtube.com/shorts/oD1x982lMD4,false  ← Chưa upload
```

**Bước 3:** Kiểm tra lý do
- Nếu `title` trống → Chưa download từ YouTube
- Nếu `title` có giá trị → Download thành công nhưng upload thất bại

### Cách Sử Dụng Trong Tool

**1. Upload Videos:**
- Tool sẽ tự động scan `video/` folder
- Lấy danh sách từ file `shorts.csv` 
- Upload những video có `status=false`
- Cập nhật `status=true` sau khi upload thành công

**2. Kiểm Tra Progress:**
- Mở file CSV corresponding với email
- Đếm số dòng có `status=true` (đã upload)
- So sánh với `status=false` (còn lại)

**3. View & Edit CSV:**
- Dùng **Excel** hoặc **Google Sheets** để mở file
- CSV format dễ edit manual nếu cần

---

## 2. 🍪 FILE COOKIES.TXT - Quản Lý Cookie YouTube

### Cấu Trúc File

File `cookies.txt` là Netscape cookie format:
```
Domain          | Flag | Path | Secure | Expiry | Cookie Name | Cookie Value
.youtube.com    | TRUE | /    | TRUE   | 1784739049 | DEVICE_INFO | ChxOelU1Tmp...
.youtube.com    | TRUE | /    | TRUE   | 1769187722 | GPS | 1
```

### Cookie Có Tác Dụng Gì?

- ✅ **Bypass rate limiting** trên YouTube
- ✅ **Tránh bị block** khi download nhiều shorts
- ✅ **Dùng chung cho tất cả accounts** (device-level cookie)
- ✅ **Không bị trùng** vì nó là session cookie chung

### Cách Thay Cookie Cho Máy Khác

#### **Phương Án 1: Copy File Cookie** (Khuyến Nghị ✅)

**Step 1:** Trên máy cũ, lấy file `cookies.txt`
```
Đường dẫn: c:\laragon\www\tool scoopz\tool_rewrite\cookies.txt
```

**Step 2:** Copy sang máy mới, đặt ở cùng folder
```
c:\laragon\www\tool scoopz\tool_rewrite\cookies.txt
```

**Step 3:** Tool sẽ tự động dùng cookie này khi download
- Không cần làm gì thêm
- Cookie tự động được load

#### **Phương Án 2: Generate Cookie Mới**

Nếu cookie cũ bị expire:

**Step 1:** Xoá file `cookies.txt` cũ
```powershell
Remove-Item cookies.txt
```

**Step 2:** Chạy tool - nó sẽ generate cookie mới
- Tool tự động download cookies từ YouTube
- Lưu vào `cookies.txt` mới

### Tại Sao Không Bị Trùng Cookie?

- Cookie là **session-based**, không account-specific
- YouTube cấp cookie dựa trên **IP + Device**, không phải account
- Tất cả accounts cùng máy dùng **1 cookie chung** (normal)
- Cookie chỉ "trùng" nếu dùng **cùng IP** + **cùng device** (đó là mục đích)

### Khi Nào Cần Thay Cookie?

| Tình Huống | Cần Thay? | Lý Do |
|-----------|----------|-------|
| Copy tool sang máy khác | ✅ YES | Máy mới = IP mới → cookie cũ expire |
| Upload trên cùng máy | ❌ NO | Cookie vẫn hợp lệ |
| Lỗi "Rate Limited" | ✅ YES | Cookie expire hoặc bị block |
| Thay IP/VPN | ✅ YES | IP mới → cookie mới cần |

---

## 3. 🔄 Quy Trình Đầy Đủ Để Tránh Trùng Cookie

### Setup Trên Máy Mới

```powershell
# 1. Copy toàn bộ folder tool
Copy-Item "tool_rewrite" -Destination "C:\path\to\machine2" -Recurse

# 2. Copy file cookies.txt từ máy cũ
Copy-Item "cookies.txt" -Destination "C:\path\to\machine2\cookies.txt"

# 3. Chạy tool - sẽ dùng cookie cũ
# Nếu expire, tool tự generate mới

# 4. Kiểm tra - không sẽ có conflict
# Vì mỗi máy = 1 IP = 1 cookie session
```

### Nếu Cần Cookie Riêng Cho Máy Khác

**Option A: Để Tool Generate Tự Động** (Dễ nhất)
```powershell
# Máy 2: Xoá file cookies.txt cũ
Remove-Item "cookies.txt"

# Chạy tool - nó generate cookie mới cho IP máy 2
```

**Option B: Download Cookie Thủ Công**
```python
# Chạy script để get cookie mới
python3 -m yt_dlp "https://www.youtube.com/shorts/xxx" \
    --save-info-json \
    --cookies "cookies_new.txt"
```

---

## 4. 📊 Cách Kiểm Tra Upload Chính Xác

### Kiểm Tra Từng Email

**Bước 1: Mở file CSV**
```
video/[email]/shorts.csv
```

**Bước 2: Filter/Sort theo Status**
```
Status = false → Cần upload lại
Status = true  → Đã upload OK
```

**Bước 3: Đếm số lượng**
```excel
=COUNTIF(D:D,"true")   → Số đã upload
=COUNTIF(D:D,"false")  → Số chưa upload
```

### Kiểm Tra Tất Cả Emails

Dùng script PowerShell:
```powershell
$totalUploaded = 0
$totalFailed = 0

Get-ChildItem "video\*\shorts.csv" | ForEach-Object {
    $csv = Import-Csv $_
    $email = $_.Directory.Name
    $uploaded = @($csv | Where-Object { $_.status -eq "true" }).Count
    $failed = @($csv | Where-Object { $_.status -eq "false" }).Count
    
    Write-Host "$email: ✅$uploaded | ❌$failed"
    $totalUploaded += $uploaded
    $totalFailed += $failed
}

Write-Host ""
Write-Host "TỔNG: ✅$totalUploaded | ❌$totalFailed"
```

---

## 5. 🔧 Troubleshooting

### Vấn Đề: Videos bị trùng upload

**Nguyên nhân:**
- Cookie cũ vẫn được dùng
- Rate limit chưa reset

**Giải pháp:**
1. Xoá file `cookies.txt`
2. Đợi 1-2 giờ
3. Chạy tool lại - sẽ generate cookie mới

### Vấn Đề: CSV file hiển thị lỗi

**Cách fix:**
1. Mở bằng Excel → File → Save As → Chọn format CSV UTF-8
2. Hoặc dùng Notepad++ → Encoding → UTF-8

### Vấn Đề: Tool không load cookie

**Kiểm tra:**
```powershell
# Xem file cookies.txt có tồn tại không
Test-Path "cookies.txt"

# Xem content
Get-Content "cookies.txt" | head -5
```

---

## 📝 Tóm Tắt

| Thành Phần | Mục Đích | Cách Dùng |
|-----------|---------|----------|
| **video/** folder | Lưu danh sách video từng email | Auto scan, xem file CSV |
| **shorts.csv** | Theo dõi status upload (true/false) | Mở bằng Excel, xem cột status |
| **cookies.txt** | YouTube session cookie chung | Copy sang máy khác, hoặc delete để generate mới |

## ✅ Setup Hoàn Chỉnh

- ✅ Folder video: 201 emails sẵn sàng
- ✅ CSV files: Tracking status upload từng email
- ✅ Cookie file: Shared YouTube session
- ✅ Sẵn sàng chạy multi-machine mà không trùng cookie!

---

**Cần help? Check logs trong folder `logs/` để xem chi tiết upload từng email.**
