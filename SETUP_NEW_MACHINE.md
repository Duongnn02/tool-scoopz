# 🚀 SETUP TOOL TRÊN MÁY KHÁC

## ⚠️ LỖI: pip is not recognized

**Lỗi này xảy ra khi:**

- Python chưa cài đặt
- Python chưa được thêm vào PATH
- Cần dùng `python -m pip` thay vì `pip`

---

## ✅ CÁCH FIX (3 CÁCH)

### **CÁCH 1: Dùng `python -m pip` (RECOMMENDED)**

```powershell
# Vào folder tool_rewrite
cd C:\Users\Admin\Downloads\Telegram Desktop\tool_rewrite\tool_rewrite

# Install requirements bằng python module
python -m pip install -r requirements.txt
```

**Tại sao?** Cách này luôn hoạt động vì nó gọi `pip` qua Python interpreter.

---

### **CÁCH 2: Dùng Script Setup (AUTO - RECOMMENDED)**

**Tải file này về cùng folder dist:**

- `setup_install.ps1` (script PowerShell auto-install)

**Cách chạy:**

```powershell
# 1. Right-click vào folder tool_rewrite
# 2. Chọn "Open PowerShell window here"
# 3. Chạy:
.\setup_install.ps1
```

**Script sẽ tự động:**

- ✅ Check Python installed
- ✅ Check pip available
- ✅ Install all requirements
- ✅ Create virtual environment (nếu cần)

---

### **CÁCH 3: Cài đặt Python đầy đủ**

Nếu Python chưa cài:

1. **Download Python 3.10+** từ python.org
2. **Cài đặt & CHECK:** `Add Python to PATH`
3. **Restart PowerShell**
4. **Chạy lại:**
   ```powershell
   pip install -r requirements.txt
   ```

---

## 📋 STEP-BY-STEP GUIDE

### **Bước 1: Kiểm tra Python**

```powershell
python --version
```

**Output tốt:**

```
Python 3.10.6
```

**Output lỗi:**

```
python : The term 'python' is not recognized...
```

→ Python chưa cài hoặc PATH sai

---

### **Bước 2: Kiểm tra pip**

```powershell
python -m pip --version
```

**Output tốt:**

```
pip 25.3 from C:\Python310\lib\site-packages\pip (python 3.10)
```

---

### **Bước 3: Install Requirements**

**Option A - Dùng python -m pip:**

```powershell
python -m pip install -r requirements.txt
```

**Option B - Dùng setup script:**

```powershell
.\setup_install.ps1
```

---

## 🔧 ADVANCED: Tạo Virtual Environment

Nếu muốn isolated environment:

```powershell
# 1. Tạo venv
python -m venv venv

# 2. Activate venv
.\venv\Scripts\Activate.ps1

# 3. Install requirements
pip install -r requirements.txt

# 4. Chạy tool
python gui_app.py
```

---

## ✅ VERIFY INSTALLATION

Kiểm tra xem install thành công không:

```powershell
python -c "import selenium; import pywinauto; import requests; import yt_dlp; print('✅ All libraries installed!')"
```

**Output:**

```
✅ All libraries installed!
```

---

## 📦 FOLDER STRUCTURE SAU KHI SETUP

```
tool_rewrite/
├── ScoopzTool.exe              ← Exe chính
├── cookies.txt                 ← Cookie YouTube
├── accounts_cache.json         ← 192 emails
├── requirements.txt            ← Libraries list
├── setup_install.ps1           ← Setup script
├── logs/                        ← Logs (auto-create)
├── video/                       ← Video data (43 MB)
└── ... (source files)
```

---

## 🎯 CHỌN CÁCH NHANH NHẤT

| Cách       | Lệnh                                        | Tốc độ          | Khó độ      |
| ---------- | ------------------------------------------- | --------------- | ----------- |
| **Cách 1** | `python -m pip install -r requirements.txt` | ⚡ Nhanh        | ⭐ Dễ       |
| **Cách 2** | `.\setup_install.ps1`                       | ⚡⚡ Siêu nhanh | ⭐⭐ Rất dễ |
| **Cách 3** | Cài Python mới + pip                        | 🐢 Chậm         | ⭐⭐⭐ Khó  |

---

## 💡 TROUBLESHOOTING

### Lỗi: "permission denied"

```powershell
# Fix:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup_install.ps1
```

### Lỗi: "Module not found"

```powershell
# Kiểm tra install:
python -m pip list

# Nếu thiếu, install lại:
python -m pip install -r requirements.txt --upgrade
```

### Lỗi: "Port already in use"

```powershell
# Restart PowerShell, hoặc kill process:
Get-Process | Where-Object {$_.Name -like "*python*"} | Stop-Process
```

---

## 📞 CONTACT IF ISSUES

Nếu vẫn lỗi, check:

1. Python version >= 3.8
2. Internet connection (download packages)
3. Administrator privileges
4. Antivirus không block pip
