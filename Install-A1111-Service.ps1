# =============================================================================
# Install-A1111-Service.ps1
# Installs Automatic1111 (via Stability Matrix) as a Windows service using NSSM.
# Run this script as Administrator.
# =============================================================================

#Requires -RunAsAdministrator

# ---------------------------------------------------------------------------
# CONFIGURATION — adjust these if your paths differ
# ---------------------------------------------------------------------------

# Where Stability Matrix installed A1111
$A1111Root    = "C:\AI\StabilityMatrix\Data\Packages\stable-diffusion-webui"

# Python executable inside A1111's venv
$PythonExe    = "$A1111Root\venv\Scripts\python.exe"

# A1111 launch script
$LaunchScript = "$A1111Root\launch.py"

# A1111 launch arguments
# --api           : expose REST API on port 7860 (required for bot)
# --medvram       : keep VRAM under 8GB for RTX 3060 Ti
# --no-half-vae   : prevent washed-out colors on 8GB cards
# --nowebui       : suppress browser UI window (headless mode)
# --port 7860     : explicit port (default, change if needed)
$LaunchArgs   = "--api --medvram --no-half-vae --nowebui --port 7860"

# Service config
$ServiceName  = "A1111-WebUI"
$ServiceDesc  = "Automatic1111 Stable Diffusion WebUI API (headless)"
$LogDir       = "C:\AI\StabilityMatrix\Logs"

# NSSM path — if NSSM is already installed for your bot service, it's probably here:
$NssmExe      = "C:\nssm\nssm.exe"

# ---------------------------------------------------------------------------
# Validate paths
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== A1111 Windows Service Installer ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $NssmExe)) {
    Write-Host "NSSM not found at $NssmExe" -ForegroundColor Yellow
    Write-Host "Downloading NSSM..." -ForegroundColor Cyan
    $NssmZip = "$env:TEMP\nssm.zip"
    Invoke-WebRequest -Uri "https://nssm.cc/release/nssm-2.24.zip" -OutFile $NssmZip
    Expand-Archive -Path $NssmZip -DestinationPath "$env:TEMP\nssm_extract" -Force
    $NssmBin = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" |
        Where-Object { $_.FullName -match "win64" } | Select-Object -First 1
    if (-not $NssmBin) {
        $NssmBin = Get-ChildItem "$env:TEMP\nssm_extract" -Recurse -Filter "nssm.exe" | Select-Object -First 1
    }
    New-Item -ItemType Directory -Path "C:\nssm" -Force | Out-Null
    Copy-Item $NssmBin.FullName -Destination $NssmExe -Force
    Write-Host "NSSM installed to $NssmExe" -ForegroundColor Green
}

if (-not (Test-Path $PythonExe)) {
    Write-Host ""
    Write-Host "ERROR: Python not found at:" -ForegroundColor Red
    Write-Host "  $PythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Check that Stability Matrix installed A1111 at: $A1111Root" -ForegroundColor Yellow
    Write-Host "If it's in a different location, edit the `$A1111Root variable at the top of this script." -ForegroundColor Yellow
    exit 1
}

if (-not (Test-Path $LaunchScript)) {
    Write-Host ""
    Write-Host "ERROR: launch.py not found at:" -ForegroundColor Red
    Write-Host "  $LaunchScript" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Write-Host "Log directory: $LogDir" -ForegroundColor Gray

# ---------------------------------------------------------------------------
# Remove existing service if present
# ---------------------------------------------------------------------------

$existing = & $NssmExe status $ServiceName 2>&1
if ($existing -notmatch "can't open service") {
    Write-Host "Removing existing service '$ServiceName'..." -ForegroundColor Yellow
    & $NssmExe stop $ServiceName 2>&1 | Out-Null
    & $NssmExe remove $ServiceName confirm 2>&1 | Out-Null
    Start-Sleep -Seconds 2
}

# ---------------------------------------------------------------------------
# Install service
# ---------------------------------------------------------------------------

Write-Host "Installing service '$ServiceName'..." -ForegroundColor Cyan

& $NssmExe install $ServiceName $PythonExe
& $NssmExe set $ServiceName AppParameters "$LaunchScript $LaunchArgs"
& $NssmExe set $ServiceName AppDirectory $A1111Root
& $NssmExe set $ServiceName Description $ServiceDesc
& $NssmExe set $ServiceName Start SERVICE_AUTO_START

# Logging
& $NssmExe set $ServiceName AppStdout "$LogDir\a1111-stdout.log"
& $NssmExe set $ServiceName AppStderr "$LogDir\a1111-stderr.log"
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateSeconds 86400
& $NssmExe set $ServiceName AppRotateBytes 10485760

# Restart on failure (wait 10s before retry)
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 10000

# ---------------------------------------------------------------------------
# Start service
# ---------------------------------------------------------------------------

Write-Host "Starting service..." -ForegroundColor Cyan
& $NssmExe start $ServiceName

Start-Sleep -Seconds 5
$status = & $NssmExe status $ServiceName
Write-Host ""
Write-Host "Service status: $status" -ForegroundColor $(if ($status -match "RUNNING") { "Green" } else { "Yellow" })

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Green
Write-Host ""
Write-Host "Service name  : $ServiceName" -ForegroundColor White
Write-Host "API endpoint  : http://127.0.0.1:7860" -ForegroundColor White
Write-Host "Logs          : $LogDir\a1111-stdout.log" -ForegroundColor White
Write-Host "Headless mode : --nowebui (no browser window)" -ForegroundColor White
Write-Host ""
Write-Host "Manage with:" -ForegroundColor Gray
Write-Host "  Start  : nssm start $ServiceName" -ForegroundColor Gray
Write-Host "  Stop   : nssm stop $ServiceName" -ForegroundColor Gray
Write-Host "  Status : nssm status $ServiceName" -ForegroundColor Gray
Write-Host "  Remove : nssm remove $ServiceName confirm" -ForegroundColor Gray
Write-Host ""
Write-Host "NOTE: A1111 takes 30-60 seconds to fully load on first start." -ForegroundColor Yellow
Write-Host "The bot already waits up to 3 minutes for the API to respond." -ForegroundColor Yellow
Write-Host ""
