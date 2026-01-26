#!/usr/bin/env pwsh

# Script check upload status

param(
    [switch]$Summary,
    [switch]$Details,
    [string]$Email = ""
)

$videoPath = "./video"

if (-not (Test-Path $videoPath)) {
    Write-Host "No video folder found" -ForegroundColor Red
    exit 1
}

$totalEmails = 0
$totalUploaded = 0
$totalFailed = 0
$emailStats = @()

Write-Host ""
Write-Host "Scanning upload status..." -ForegroundColor Cyan
Write-Host ""

Get-ChildItem "$videoPath\*\shorts.csv" | ForEach-Object {
    $csvPath = $_
    $emailName = $_.Directory.Name
    
    try {
        $csv = Import-Csv $csvPath -ErrorAction Stop
        $uploaded = @($csv | Where-Object { $_.status -eq "true" }).Count
        $failed = @($csv | Where-Object { $_.status -eq "false" }).Count
        $total = $csv.Count
        
        $percentUploaded = if ($total -gt 0) { [Math]::Round(($uploaded / $total) * 100, 1) } else { 0 }
        
        $emailStats += @{
            Email    = $emailName
            Uploaded = $uploaded
            Failed   = $failed
            Total    = $total
            Percent  = $percentUploaded
        }
        
        $totalEmails += 1
        $totalUploaded += $uploaded
        $totalFailed += $failed
        
        # Display individual email status
        if ($Details -or ($Email -and $Email -eq $emailName)) {
            $statusIcon = if ($failed -eq 0) { "[OK]" } else { "[WARN]" }
            $color = if ($failed -eq 0) { "Green" } else { "Yellow" }
            Write-Host "$statusIcon $emailName" -ForegroundColor $color
            Write-Host "   Uploaded: $uploaded | Failed: $failed | Total: $total (Percent: $percentUploaded)" -ForegroundColor Gray
        }
    }
    catch {
        Write-Host "[ERR] Error reading $emailName/shorts.csv" -ForegroundColor Red
    }
}

# Display Summary
if ($Summary -or -not $Details) {
    Write-Host ""
    Write-Host "===== SUMMARY =====" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Total Emails: $totalEmails" -ForegroundColor Yellow
    Write-Host "[OK] Videos Uploaded: $totalUploaded" -ForegroundColor Green
    Write-Host "[FAIL] Videos Failed: $totalFailed" -ForegroundColor Red
    Write-Host ""
    
    $totalVideos = $totalUploaded + $totalFailed
    if ($totalVideos -gt 0) {
        $percentTotal = [Math]::Round(($totalUploaded / $totalVideos) * 100, 1)
        Write-Host "Success Rate: $percentTotal percent" -ForegroundColor $(if ($percentTotal -ge 90) { "Green" } else { "Yellow" })
    }
    
    Write-Host ""
    Write-Host "==================" -ForegroundColor Cyan
}

# Top failed emails
if ($totalFailed -gt 0) {
    Write-Host ""
    Write-Host "[WARN] EMAILS NEED RETRY (have unfinished videos):" -ForegroundColor Yellow
    Write-Host ""
    
    $emailStats | Where-Object { $_.Failed -gt 0 } | Sort-Object Failed -Descending | ForEach-Object {
        Write-Host "  - $($_.Email): $($_.Failed) videos" -ForegroundColor Yellow
    }
    Write-Host ""
}

Write-Host ""
