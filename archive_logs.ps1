# ============================================================
# archive_logs.ps1 — Compress and archive bot logs
# Run from: C:\Users\akodoreign\Desktop\chatGPT-discord-bot
# ============================================================

$LogDir     = ".\logs"
$ArchiveDir = ".\campaign_docs\archives\logs"
$Timestamp  = Get-Date -Format "yyyy-MM-dd_HHmm"

# Ensure archive directory exists
if (-not (Test-Path $ArchiveDir)) {
    New-Item -ItemType Directory -Path $ArchiveDir -Force | Out-Null
    Write-Host "Created archive directory: $ArchiveDir" -ForegroundColor Green
}

$StderrLog = Join-Path $LogDir "bot_stderr.log"

if (-not (Test-Path $StderrLog)) {
    Write-Host "No stderr log found at $StderrLog" -ForegroundColor Yellow
    exit 0
}

$LogSize = (Get-Item $StderrLog).Length
if ($LogSize -eq 0) {
    Write-Host "Log file is empty — nothing to archive" -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Log Archival — $Timestamp" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Parse key stats from log
Write-Host "Parsing log events..." -ForegroundColor Yellow
$LogContent = Get-Content $StderrLog -Raw -ErrorAction SilentlyContinue

$Stats = @{
    TotalLines      = (Get-Content $StderrLog | Measure-Object -Line).Lines
    Errors          = ([regex]::Matches($LogContent, "ERROR")).Count
    Warnings        = ([regex]::Matches($LogContent, "WARN")).Count
    Bulletins       = ([regex]::Matches($LogContent, "Bulletin posted")).Count
    StoryImages     = ([regex]::Matches($LogContent, "Story image posted")).Count
    LifecycleRuns   = ([regex]::Matches($LogContent, "Lifecycle complete")).Count
    BotStarts       = ([regex]::Matches($LogContent, "TOWER BOT STARTED")).Count
    Reconnects      = ([regex]::Matches($LogContent, "RESUMED session")).Count
}

# Generate summary
$Summary = @"
============================================================
BOT LOG SUMMARY — Archived $Timestamp
============================================================

Log file size: $([math]::Round($LogSize / 1024, 1)) KB
Total lines:   $($Stats.TotalLines)

ACTIVITY SUMMARY
  Bulletins posted:     $($Stats.Bulletins)
  Story images:         $($Stats.StoryImages)
  NPC lifecycle runs:   $($Stats.LifecycleRuns)
  
SESSION INFO
  Bot starts:           $($Stats.BotStarts)
  Reconnects:           $($Stats.Reconnects)

ISSUES
  Errors logged:        $($Stats.Errors)
  Warnings logged:      $($Stats.Warnings)

============================================================
"@

Write-Host $Summary

# Save summary
$SummaryPath = Join-Path $ArchiveDir "summary_$Timestamp.txt"
$Summary | Out-File -FilePath $SummaryPath -Encoding UTF8
Write-Host "Summary saved: $SummaryPath" -ForegroundColor Green

# Compress log with gzip via .NET
$ArchivePath = Join-Path $ArchiveDir "bot_stderr_$Timestamp.log.gz"
Write-Host "Compressing log to: $ArchivePath" -ForegroundColor Yellow

try {
    $SourceStream = [System.IO.File]::OpenRead($StderrLog)
    $DestStream   = [System.IO.File]::Create($ArchivePath)
    $GzipStream   = New-Object System.IO.Compression.GZipStream($DestStream, [System.IO.Compression.CompressionLevel]::Optimal)
    
    $SourceStream.CopyTo($GzipStream)
    
    $GzipStream.Close()
    $DestStream.Close()
    $SourceStream.Close()
    
    $CompressedSize = (Get-Item $ArchivePath).Length
    $Ratio = [math]::Round((1 - $CompressedSize / $LogSize) * 100, 0)
    
    Write-Host "Compressed: $([math]::Round($LogSize / 1024, 1)) KB -> $([math]::Round($CompressedSize / 1024, 1)) KB ($Ratio% reduction)" -ForegroundColor Green
    
    # Clear original log
    $RotateHeader = @"
# Log rotated at $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# Previous log archived to: bot_stderr_$Timestamp.log.gz

"@
    $RotateHeader | Out-File -FilePath $StderrLog -Encoding UTF8
    Write-Host "Original log cleared and rotated" -ForegroundColor Green
    
} catch {
    Write-Host "Compression failed: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Archive complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Archives saved to: $ArchiveDir" -ForegroundColor Cyan
Get-ChildItem $ArchiveDir | Format-Table Name, Length, LastWriteTime -AutoSize
