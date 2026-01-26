# 🎯 Cookie Management - Hình Ảnh Minh Họa

## Scenario 1: Máy Mới Lần Đầu (Máy Cũ Không Dùng Nữa)

```
┌─────────────────────────────────────────────────────────┐
│              MÁYCŨ                                      │
│  ┌─────────────────────────────────────────────────┐   │
│  │ tool_rewrite/                                   │   │
│  │ ├─ dist/ScoopzTool.exe                          │   │
│  │ ├─ video/                                       │   │
│  │ ├─ cookies.txt (IP: 192.168.1.1)               │   │
│  │ └─ ...                                          │   │
│  └─────────────────────────────────────────────────┘   │
│                      ⬇️  COPY                           │
│              Copy cookies.txt                          │
│                      ⬇️                                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│              MÁY MỚI                                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │ tool_rewrite/                                   │   │
│  │ ├─ dist/ScoopzTool.exe                          │   │
│  │ ├─ video/                                       │   │
│  │ ├─ cookies.txt (IP: 192.168.1.50) ✅ DÙNG OK   │   │
│  │ └─ ...                                          │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
│  YouTube: IP từ cookies = IP máy mới ✅ Match         │
│  → Upload OK                                           │
└─────────────────────────────────────────────────────────┘
```

**Tóm tắt:** Copy cookies.txt từ máy cũ → Dùng ngay trên máy mới ✅

---

## Scenario 2: Máy Mới + Máy Cũ Chạy Song Song (QUAN TRỌNG)

```
                        ❌ SAI (KHÔNG NÊN)

┌──────────────┐              ┌──────────────┐
│   MÁY CŨ     │              │   MÁY MỚI    │
│ IP: 1.1.1.1  │              │ IP: 2.2.2.2  │
├──────────────┤              ├──────────────┤
│ cookies.txt  │◄────────────►│ cookies.txt  │
│ (session A)  │  SAME FILE   │ (session A)  │
└──────────────┘              └──────────────┘
         ⬇️                            ⬇️
      Upload                       Upload
    từ IP 1.1.1.1              từ IP 2.2.2.2
         ⬇️                            ⬇️
    YouTube: "Wait..."
    Session A từ IP 1.1.1.1? 
    Nhưng request từ IP 2.2.2.2?
    ❌ BLOCK / RATE LIMIT
```

---

## Scenario 2: Máy Mới + Máy Cũ Chạy Song Song (CÁCH ĐÚNG ✅)

```
                        ✅ ĐÚNG (KHUYÊN)

┌──────────────┐              ┌──────────────┐
│   MÁY CŨ     │              │   MÁY MỚI    │
│ IP: 1.1.1.1  │              │ IP: 2.2.2.2  │
├──────────────┤              ├──────────────┤
│ cookies.txt  │              │ cookies.txt  │
│ (session A)  │              │ (session B)  │
│ ← IP 1.1.1.1 │              │ ← IP 2.2.2.2 │
└──────────────┘              └──────────────┘
         ⬇️                            ⬇️
      Upload                       Upload
    từ IP 1.1.1.1              từ IP 2.2.2.2
         ⬇️                            ⬇️
    YouTube: Session A ✅
    IP 1.1.1.1 match!
    
    YouTube: Session B ✅
    IP 2.2.2.2 match!
    
    ✅ UPLOAD OK (Both)
```

**Tóm tắt:** Mỗi máy = 1 cookies.txt riêng → Không conflict ✅

---

## Setup Steps - Visual

```
MÁYCŨ
│
├─ Step 1: Backup
│  └─ Compress-Archive tool_rewrite
│
├─ Step 2: Copy
│  └─ Copy zip → USB / Network
│
└─ Done


MÁYMỚI
│
├─ Step 1: Extract
│  └─ Expand-Archive tool_rewrite.zip
│
├─ Step 2: Quyết định Cookie
│  │
│  ├─ OPTION A: Copy cookies.txt (máy cũ không dùng)
│  │  └─ Copy "cookies.txt" từ USB
│  │
│  └─ OPTION B: Generate mới (máy cũ vẫn dùng)
│     └─ Remove-Item "cookies.txt"
│
├─ Step 3: Chạy
│  └─ .\dist\ScoopzTool.exe
│
└─ Done! (Cookie auto-handled)
```

---

## Cookie Lifecycle - Timeline

```
┌──────────────────────────────────────────────────────────┐
│            COOKIE LIFETIME                               │
├──────────────────────────────────────────────────────────┤
│                                                          │
│ Day 0: Create                                            │
│ ├─ Tool download từ YouTube                             │
│ ├─ Save vào cookies.txt                                 │
│ └─ Status: ✅ FRESH                                      │
│                                                          │
│ Day 1-29: Normal Usage                                  │
│ ├─ Upload: ✅ OK                                         │
│ ├─ Download: ✅ OK                                       │
│ └─ Status: ✅ VALID                                      │
│                                                          │
│ Day 30: Warning Zone                                    │
│ ├─ Upload: ⚠️ SLOWER                                     │
│ ├─ YouTube: May ask for refresh                         │
│ └─ Status: ⚠️ AGING                                      │
│                                                          │
│ Day 60-90: Expiry Zone                                  │
│ ├─ Upload: ❌ FAIL / RATE LIMIT                          │
│ ├─ Download: ❌ FAIL                                     │
│ └─ Status: ❌ EXPIRED                                    │
│                                                          │
│ Day 90+: Must Refresh                                   │
│ ├─ Delete cookies.txt                                  │
│ ├─ Tool generate cookie mới                             │
│ └─ Status: ✅ FRESH (Reset to Day 0)                    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Timeline for máy mới:**
- Copy cookies từ máy cũ (Day 1-29): ✅ Dùng OK
- Copy cookies từ máy cũ (Day 60+): ❌ Expired
- Delete + Generate mới: ✅ Reset, dùng OK

---

## Decision Tree - Chọn Cách Nào?

```
┌─ Dùng tool trên máy mới?
│
├─ Máy cũ còn dùng không?
│  │
│  ├─ YES (2+ máy chạy song song)
│  │  │
│  │  ├─ Delete cookies.txt
│  │  ├─ Run tool
│  │  └─ Generate cookie mới ← MỖI MÁY RIÊNG
│  │
│  └─ NO (máy cũ không dùng nữa)
│     │
│     ├─ Copy cookies.txt từ máy cũ
│     ├─ Run tool
│     └─ Dùng cookie cũ (nếu <30 ngày) ← OK
│        OR Generate mới (nếu >30 ngày) ← AN TOÀN
│
└─ DONE!
```

---

## ⚡ Quick Command Reference

### Máy Cũ - Chuẩn Bị

```powershell
# 1. Vào folder
cd "C:\laragon\www\tool scoopz\tool_rewrite"

# 2. Backup
Compress-Archive -Path "." -DestinationPath "tool_backup.zip" -Force

# 3. Copy qua USB (D:\ là ổ USB)
Copy-Item "tool_backup.zip" "D:\backup\"
Copy-Item "cookies.txt" "D:\backup\"  # Optional
```

### Máy Mới - Extract & Setup

```powershell
# 1. Extract
Expand-Archive "D:\backup\tool_backup.zip" -DestinationPath "C:\laragon\www\tool scoopz\tool_rewrite"

# 2. Vào folder
cd "C:\laragon\www\tool scoopz\tool_rewrite"

# 3A. Nếu máy cũ không dùng: Copy cookies cũ
Copy-Item "D:\backup\cookies.txt" "cookies.txt"

# 3B. Nếu máy cũ vẫn dùng: Delete để generate mới
Remove-Item "cookies.txt" -Force

# 4. Chạy tool
.\dist\ScoopzTool.exe
```

---

## 🚨 Red Flags - Detect Cookie Problem

```
Triệu chứng                 | Nguyên nhân          | Fix
---------------------------|----------------------|------------------
Upload fails suddenly       | Cookie expire        | Delete + wait 2h
"Rate limited" error        | Cookie invalid       | Delete + wait 4h
Works 1 máy, fail 1 máy    | Same cookie, diff IP | Delete on 2nd machine
Download "timeout"          | Old cookie + old IP  | Delete + generate new
CSV not updating            | Permission or lock   | Close Excel + retry
```

---

## 📊 Cost Comparison

### Approach A: Copy Exe + cookies.txt
```
Setup Time: 2 min
Disk Space: 28 MB
Python Needed: NO
Cookie Freshness: ✅ (from old machine)
Risk: LOW
```

### Approach B: Copy Source + Generate Cookie
```
Setup Time: 10 min (install Python + venv)
Disk Space: 500 MB (Python)
Python Needed: YES
Cookie Freshness: ✅ (auto-fresh)
Risk: LOW (safer if old machine expired)
```

**Khuyến Nghị:** Approach A (Exe) - nhanh, dễ, an toàn ✅

---

## 🎓 Why Multiple Machines Need Separate Cookies

**YouTube Session Security:**
```
YouTube không cho phép:
1 session token (cookie) → được dùng từ 2 IPs khác nhau cùng lúc

Vì sao?
- Bảo vệ account từ account hijacking
- Nếu token bị steal, hacker phải dùng từ IP khác
- YouTube detect: "Wait, này IP A → nay IP B? Block!"

Fix:
- 1 máy = 1 IP = 1 session = 1 cookie
- Nếu 2 máy: 2 IPs = 2 sessions = 2 cookies
```

---

## 💡 Pro Tips

1. **Nếu làm việc với 10+ máy:**
   - Setup Python + venv trên mỗi máy
   - Để nó auto-generate cookie riêng
   - Không cần quản lý manual

2. **Nếu máy nước ngoài (khác ISP/VPN):**
   - Delete cookies.txt
   - Generate lại
   - IP thay đổi → Cookie phải thay

3. **Nếu upload nhanh (500+ videos/ngày):**
   - Có thể YouTube rate limit ngay cả với fresh cookie
   - Solution: Tăng số máy, mỗi máy upload 100 videos
   - Chia load đều

4. **Nếu chạy ở datacenter/server:**
   - Cài proxy rotation (nếu cần)
   - Mỗi request = IP khác = Cookie khác
   - Dùng nhiều cookies.txt files

---

**Bottom Line:**
- ✅ Copy exe + toàn bộ folder → Chạy ngay (Approach A)
- ✅ Nếu 2+ máy chạy → Delete cookies.txt trên máy mới (generate riêng)
- ✅ Không bao giờ copy 1 cookies.txt dùng trên 2+ máy cùng lúc
- ✅ Tool tự động handle cookie lifecycle → Yên tâm sử dụng
