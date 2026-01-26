#!/usr/bin/env pwsh

# Script check va diagnose cookie status

Write-Host ""
Write-Host "COOKIE DIAGNOSTIC TOOL" -ForegroundColor Cyan
Write-Host "======================" -ForegroundColor Cyan
Write-Host ""

# Check if cookies.txt exists
if (Test-Path "cookies.txt") {
    $fileSize = (Get-Item "cookies.txt").Length
    $lastModified = (Get-Item "cookies.txt").LastWriteTime
    $daysSinceModified = ((Get-Date) - $lastModified).Days
    
    Write-Host "[OK] cookies.txt found" -ForegroundColor Green
    Write-Host "  Size: $fileSize bytes" -ForegroundColor Gray
    Write-Host "  Last modified: $lastModified" -ForegroundColor Gray
    Write-Host "  Age: $daysSinceModified days" -ForegroundColor Gray
    
    Write-Host ""
    
    # Analyze cookie age
    if ($daysSinceModified -lt 7) {
        Write-Host "Status: FRESH (0-7 days)" -ForegroundColor Green
        Write-Host "Action: Safe to use - copy to new machine OK" -ForegroundColor Green
    }
    elseif ($daysSinceModified -lt 30) {
        Write-Host "Status: VALID (7-30 days)" -ForegroundColor Green
        Write-Host "Action: Can use, but consider regenerating on new machine" -ForegroundColor Yellow
    }
    elseif ($daysSinceModified -lt 60) {
        Write-Host "Status: AGING (30-60 days)" -ForegroundColor Yellow
        Write-Host "Action: Consider refreshing, may face rate limiting soon" -ForegroundColor Yellow
    }
    else {
        Write-Host "Status: EXPIRED (60+ days)" -ForegroundColor Red
        Write-Host "Action: DELETE and regenerate new cookie" -ForegroundColor Red
        Write-Host ""
        Write-Host "How to fix:" -ForegroundColor Cyan
        Write-Host "  Remove-Item 'cookies.txt' -Force" -ForegroundColor Gray
        Write-Host "  .\dist\ScoopzTool.exe  # Will generate new cookie" -ForegroundColor Gray
    }
}
else {
    Write-Host "[WARN] cookies.txt NOT found" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Action: Tool will generate new cookie when you run it:" -ForegroundColor Cyan
    Write-Host "  .\dist\ScoopzTool.exe" -ForegroundColor Gray
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Check current IP
Write-Host "Network Information:" -ForegroundColor Yellow
try {
    $ipAddress = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.PrefixOrigin -eq "Dhcp" -or $_.PrefixOrigin -eq "Manual"} | Select-Object -First 1 -ExpandProperty IPAddress)
    Write-Host "  Current IP: $ipAddress" -ForegroundColor Gray
    Write-Host "  Note: This IP should match cookie IP after generation" -ForegroundColor Gray
}
catch {
    Write-Host "  Could not determine IP" -ForegroundColor Gray
}

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""

# Multi-machine check
Write-Host "Multi-Machine Setup:" -ForegroundColor Yellow
Write-Host "  If running on 2+ machines:" -ForegroundColor Gray
Write-Host "    1. Each machine needs its OWN cookies.txt" -ForegroundColor Gray
Write-Host "    2. Delete cookies.txt on new machine" -ForegroundColor Gray
Write-Host "    3. Run tool to generate NEW cookie for that IP" -ForegroundColor Gray
Write-Host "    4. Do NOT copy same cookies.txt to multiple machines" -ForegroundColor Red -BackgroundColor Black
Write-Host ""

Write-Host "Example Workflow:" -ForegroundColor Cyan
Write-Host "  Machine A (IP 192.168.1.1):" -ForegroundColor Gray
Write-Host "    - Has cookies.txt A" -ForegroundColor Gray
Write-Host "    - Keep as-is, continue uploading" -ForegroundColor Gray
Write-Host ""
Write-Host "  Machine B (IP 192.168.1.2):" -ForegroundColor Gray
Write-Host "    - Remove-Item 'cookies.txt'" -ForegroundColor Gray
Write-Host "    - .\dist\ScoopzTool.exe (generates cookies.txt B)" -ForegroundColor Gray
Write-Host ""
Write-Host "  Result: Machine A + B upload in parallel, no conflict!" -ForegroundColor Green

Write-Host ""
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
