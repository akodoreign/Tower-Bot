# =============================================================================
# Tower of Last Chance Bot — Windows Service Installer
# Run this script ONCE as Administrator to register the bot as a service.
# After that, the bot starts automatically on boot and restarts if it crashes.
# =============================================================================
# Usage:
#   Right-click PowerShell → Run as Administrator
#   cd C:\Users\akodoreign\Desktop\chatGPT-discord-bot
#   .\install_bot_service.ps1
# =============================================================================

$ServiceName    = "TowerBotService"
$DisplayName    = "Tower of Last Chance Discord Bot"
$Description    = "Runs the Tower of Last Chance Discord bot. Auto-restarts on crash."
$BotDir         = "C:\Users\akodoreign\Desktop\chatGPT-discord-bot"
$PythonExe      = (Get-Command py).Source   # resolves full path to py launcher
$MainScript     = "$BotDir\main.py"
$LogDir         = "$BotDir\logs"
$NssmExe        = "$BotDir\nssm.exe"
$NssmUrl        = "https://nssm.cc/release/nssm-2.24.zip"
$NssmZip        = "$env:TEMP\nssm.zip"
$NssmExtracted  = "$env:TEMP\nssm_extracted"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Write-Step($msg) {
    Write-Host "`n>> $msg" -ForegroundColor Cyan
}

function Write-OK($msg) {
    Write-Host "   OK: $msg" -ForegroundColor Green
}

function Write-Fail($msg) {
    Write-Host "   FAIL: $msg" -ForegroundColor Red
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Check admin
# ---------------------------------------------------------------------------

Write-Step "Checking administrator privileges"
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Fail "Please re-run this script as Administrator (right-click PowerShell → Run as Administrator)."
}
Write-OK "Running as Administrator"

# ---------------------------------------------------------------------------
# 2. Verify bot directory and main.py exist
# ---------------------------------------------------------------------------

Write-Step "Verifying bot directory"
if (-not (Test-Path $BotDir)) { Write-Fail "Bot directory not found: $BotDir" }
if (-not (Test-Path $MainScript)) { Write-Fail "main.py not found at: $MainScript" }
Write-OK "Bot directory OK"

# ---------------------------------------------------------------------------
# 3. Create logs directory
# ---------------------------------------------------------------------------

Write-Step "Creating logs directory"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
Write-OK "Logs directory: $LogDir"

# ---------------------------------------------------------------------------
# 4. Download NSSM if not present
#    NSSM (Non-Sucking Service Manager) wraps any exe as a Windows service
#    with built-in restart-on-crash support.
# ---------------------------------------------------------------------------

Write-Step "Checking for NSSM (service manager)"
if (-not (Test-Path $NssmExe)) {
    Write-Host "   Downloading NSSM..." -ForegroundColor Yellow
    try {
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing
        Expand-Archive -Path $NssmZip -DestinationPath $NssmExtracted -Force
        # NSSM zip contains win32/win64 subdirs — grab the 64-bit one
        $NssmBin = Get-ChildItem -Path $NssmExtracted -Recurse -Filter "nssm.exe" |
                   Where-Object { $_.FullName -match "win64" } |
                   Select-Object -First 1
        if (-not $NssmBin) {
            # Fallback: grab any nssm.exe
            $NssmBin = Get-ChildItem -Path $NssmExtracted -Recurse -Filter "nssm.exe" |
                       Select-Object -First 1
        }
        Copy-Item $NssmBin.FullName -Destination $NssmExe
        Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
        Remove-Item $NssmExtracted -Recurse -Force -ErrorAction SilentlyContinue
        Write-OK "NSSM downloaded to $NssmExe"
    } catch {
        Write-Fail "Failed to download NSSM: $_`n   Download manually from https://nssm.cc and place nssm.exe in $BotDir"
    }
} else {
    Write-OK "NSSM already present"
}

# ---------------------------------------------------------------------------
# 5. Remove existing service if present (clean reinstall)
# ---------------------------------------------------------------------------

Write-Step "Checking for existing service"
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "   Removing existing service..." -ForegroundColor Yellow
    & $NssmExe stop $ServiceName | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
    Write-OK "Old service removed"
} else {
    Write-OK "No existing service found"
}

# ---------------------------------------------------------------------------
# 6. Resolve Python 3.11 exe path
# ---------------------------------------------------------------------------

Write-Step "Resolving Python 3.11 path"
# Try py -3.11 first, then fall back to where python3.11 lives
try {
    $PythonResolved = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
} catch {
    $PythonResolved = $null
}
if (-not $PythonResolved -or -not (Test-Path $PythonResolved)) {
    Write-Fail "Could not locate Python 3.11 executable. Make sure Python 3.11 is installed and 'py' launcher is available."
}
Write-OK "Python 3.11: $PythonResolved"

# ---------------------------------------------------------------------------
# 7. Install the service via NSSM
# ---------------------------------------------------------------------------

Write-Step "Installing service: $DisplayName"

& $NssmExe install $ServiceName $PythonResolved
& $NssmExe set $ServiceName AppParameters        $MainScript
& $NssmExe set $ServiceName AppDirectory         $BotDir
& $NssmExe set $ServiceName DisplayName          $DisplayName
& $NssmExe set $ServiceName Description          $Description
& $NssmExe set $ServiceName Start                SERVICE_AUTO_START

# Restart behaviour: restart immediately on crash, up to 3 times, then wait 60s
& $NssmExe set $ServiceName AppRestartDelay      5000          # 5 second delay before restart
& $NssmExe set $ServiceName AppThrottle          10000         # don't restart faster than 10s
& $NssmExe set $ServiceName AppExit              Default       Restart

# Stdout / stderr → log files (rotated by NSSM)
& $NssmExe set $ServiceName AppStdout            "$LogDir\bot_stdout.log"
& $NssmExe set $ServiceName AppStderr            "$LogDir\bot_stderr.log"
& $NssmExe set $ServiceName AppStdoutCreationDisposition Append
& $NssmExe set $ServiceName AppStderrCreationDisposition Append
& $NssmExe set $ServiceName AppRotateFiles       1
& $NssmExe set $ServiceName AppRotateSeconds     86400         # rotate logs daily
& $NssmExe set $ServiceName AppRotateBytes       10485760      # rotate at 10 MB

Write-OK "Service installed"

# ---------------------------------------------------------------------------
# 8. Start the service
# ---------------------------------------------------------------------------

Write-Step "Starting service"
& $NssmExe start $ServiceName
Start-Sleep -Seconds 3

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "Service is RUNNING"
} else {
    Write-Host "   Service did not start immediately — check logs at $LogDir" -ForegroundColor Yellow
    Write-Host "   You can also run: nssm status $ServiceName" -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host " Tower Bot Service Installed Successfully!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host " Service name : $ServiceName"
Write-Host " Starts on    : Windows boot (automatic)"
Write-Host " Restarts on  : Crash or unexpected exit (5s delay)"
Write-Host " Log files    : $LogDir\bot_stdout.log"
Write-Host "                $LogDir\bot_stderr.log"
Write-Host ""
Write-Host " Useful commands (run as Admin in PowerShell):"
Write-Host "   Start  : Start-Service $ServiceName"
Write-Host "   Stop   : Stop-Service $ServiceName"
Write-Host "   Status : Get-Service $ServiceName"
Write-Host "   Logs   : Get-Content '$LogDir\bot_stdout.log' -Tail 50 -Wait"
Write-Host "   Remove : $NssmExe remove $ServiceName confirm"
Write-Host ""