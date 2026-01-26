# -*- coding: utf-8 -*-
# ScoopzTool - Setup & Install Script
# Chạy script này để tự động setup tool trên máy mới

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   🚀 SCOOPZTOOL SETUP - AUTO INSTALL LIBRARIES                ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ============================================================================
# STEP 1: Check Python Installed
# ============================================================================

Write-Host "📍 STEP 1: Checking Python Installation..." -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor Gray

try {
    $python_version = & python --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ Python found: $python_version" -ForegroundColor Green
    } else {
        throw "Python not found"
    }
} catch {
    Write-Host "❌ ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host ""
    Write-Host "📖 SOLUTION:" -ForegroundColor Yellow
    Write-Host "  1. Download Python 3.10+ from: https://www.python.org/downloads/" -ForegroundColor White
    Write-Host "  2. During installation, CHECK 'Add Python to PATH'" -ForegroundColor White
    Write-Host "  3. Restart PowerShell" -ForegroundColor White
    Write-Host "  4. Run this script again" -ForegroundColor White
    Write-Host ""
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 2: Check pip Available
# ============================================================================

Write-Host "📍 STEP 2: Checking pip..." -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor Gray

try {
    $pip_version = & python -m pip --version 2>&1
    Write-Host "✅ pip found: $pip_version" -ForegroundColor Green
} catch {
    Write-Host "❌ ERROR: pip is not available" -ForegroundColor Red
    Write-Host "  Trying to reinstall pip..." -ForegroundColor Yellow
    & python -m ensurepip --upgrade
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✅ pip reinstalled successfully" -ForegroundColor Green
    } else {
        Write-Host "❌ Failed to install pip" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""

# ============================================================================
# STEP 3: Check requirements.txt exists
# ============================================================================

Write-Host "📍 STEP 3: Checking requirements.txt..." -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor Gray

$script_dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$req_file = Join-Path $script_dir "requirements.txt"

if (Test-Path $req_file) {
    Write-Host "✅ requirements.txt found: $req_file" -ForegroundColor Green
    $req_content = Get-Content $req_file | Where-Object { $_ -and -not $_.StartsWith("#") } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Host "   ($req_content libraries to install)" -ForegroundColor Gray
} else {
    Write-Host "❌ ERROR: requirements.txt not found" -ForegroundColor Red
    Write-Host "   Expected: $req_file" -ForegroundColor Yellow
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 4: Install Requirements
# ============================================================================

Write-Host "📍 STEP 4: Installing Python libraries..." -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor Gray
Write-Host ""

$start_time = Get-Date

& python -m pip install -r $req_file --upgrade 2>&1 | ForEach-Object {
    Write-Host $_
}

$install_exit = $LASTEXITCODE

$end_time = Get-Date
$duration = ($end_time - $start_time).TotalSeconds

Write-Host ""

if ($install_exit -eq 0) {
    Write-Host "✅ Installation completed successfully in ${duration}s" -ForegroundColor Green
} else {
    Write-Host "❌ Installation failed with exit code: $install_exit" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 5: Verify Installation
# ============================================================================

Write-Host "📍 STEP 5: Verifying installation..." -ForegroundColor Yellow
Write-Host "─────────────────────────────────────────────────────────────────" -ForegroundColor Gray

$test_script = @"
try:
    import selenium
    import pywinauto
    import requests
    import yt_dlp
    import openpyxl
    from bs4 import BeautifulSoup
    print('✅ All core libraries verified!')
    exit(0)
except Exception as e:
    print(f'❌ Verification failed: {e}')
    exit(1)
"@

$result = & python -c $test_script 2>&1
Write-Host $result -ForegroundColor Green

if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Verification failed" -ForegroundColor Red
    exit 1
}

Write-Host ""

# ============================================================================
# STEP 6: Summary
# ============================================================================

Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
Write-Host "✅ SETUP COMPLETE!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Yellow
Write-Host ""
Write-Host "📦 Installation Summary:" -ForegroundColor Cyan
Write-Host "  ✅ Python: Installed & verified" -ForegroundColor Green
Write-Host "  ✅ pip: Available & updated" -ForegroundColor Green
Write-Host "  ✅ Libraries: All installed successfully" -ForegroundColor Green
Write-Host "  ✅ Time elapsed: ${duration}s" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 NEXT STEPS:" -ForegroundColor Yellow
Write-Host "  1. Run ScoopzTool.exe" -ForegroundColor White
Write-Host "  2. Configure your accounts" -ForegroundColor White
Write-Host "  3. Start scanning & uploading!" -ForegroundColor White
Write-Host ""
Write-Host "📁 Folder structure:" -ForegroundColor Cyan
Write-Host "  - ScoopzTool.exe  → Main application" -ForegroundColor Gray
Write-Host "  - cookies.txt     → YouTube session" -ForegroundColor Gray
Write-Host "  - accounts_cache.json → Account configs" -ForegroundColor Gray
Write-Host "  - video/          → Video data (auto-create)" -ForegroundColor Gray
Write-Host "  - logs/           → Log files (auto-create)" -ForegroundColor Gray
Write-Host ""
Write-Host "════════════════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# Keep window open
Read-Host "Press Enter to close this window"
