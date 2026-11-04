$ServiceName = "TowerBotService"
$BotDir = $PSScriptRoot
$LogDir = $BotDir + "\logs"
$NssmExe = $BotDir + "\nssm.exe"
$MainScript = $BotDir + "\main.py"
$TunnelName = "TowerTunnel"
$CloudflaredExe = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
$TunnelConfig = "C:\cloudflared\config.yml"

Write-Host ""
Write-Host ">> Checking administrator privileges" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "   FAIL: Re-run as Administrator" -ForegroundColor Red
    exit 1
}
Write-Host "   OK: Running as Administrator" -ForegroundColor Green

Write-Host ""
Write-Host ">> Verifying bot directory" -ForegroundColor Cyan
if (-not (Test-Path $BotDir)) {
    Write-Host "   FAIL: Bot directory not found" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $MainScript)) {
    Write-Host "   FAIL: main.py not found" -ForegroundColor Red
    exit 1
}
Write-Host "   OK: Bot directory found" -ForegroundColor Green

Write-Host ""
Write-Host ">> Creating logs directory" -ForegroundColor Cyan
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
Write-Host "   OK: Logs directory ready" -ForegroundColor Green

Write-Host ""
Write-Host ">> Checking for nssm.exe" -ForegroundColor Cyan
if (-not (Test-Path $NssmExe)) {
    Write-Host "   FAIL: nssm.exe not found in $BotDir" -ForegroundColor Red
    Write-Host "   Download from https://nssm.cc, extract win64/nssm.exe into the bot folder" -ForegroundColor Yellow
    exit 1
}
Write-Host "   OK: nssm.exe found" -ForegroundColor Green

Write-Host ""
Write-Host ">> Resolving the bot's venv Python" -ForegroundColor Cyan
$PythonResolved = $BotDir + "\.venv\Scripts\python.exe"
if (-not (Test-Path $PythonResolved)) {
    Write-Host "   FAIL: .venv not found (py -3.11 -m venv .venv; .venv\Scripts\pip install -r requirements.txt)" -ForegroundColor Red
    exit 1
}
Write-Host ("   OK: " + $PythonResolved) -ForegroundColor Green

Write-Host ""
Write-Host ">> Removing existing service if present" -ForegroundColor Cyan
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    & $NssmExe stop $ServiceName | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
    Write-Host "   OK: Old service removed" -ForegroundColor Green
} else {
    Write-Host "   OK: No existing service" -ForegroundColor Green
}

Write-Host ""
Write-Host ">> Installing Cloudflare tunnel service" -ForegroundColor Cyan
if (-not (Test-Path $CloudflaredExe) -or -not (Test-Path $TunnelConfig)) {
    Write-Host "   FAIL: cloudflared or $TunnelConfig missing" -ForegroundColor Red
    exit 1
}
if (Get-Service -Name $TunnelName -ErrorAction SilentlyContinue) {
    & $NssmExe stop $TunnelName | Out-Null
    & $NssmExe remove $TunnelName confirm | Out-Null
}
& $NssmExe install $TunnelName $CloudflaredExe
& $NssmExe set $TunnelName AppParameters ("--config `"" + $TunnelConfig + "`" tunnel run")
& $NssmExe set $TunnelName DisplayName "Tower of Last Chance Dashboard Tunnel"
& $NssmExe set $TunnelName Description "Cloudflare tunnel for dashboard.tower-bot.com (started with the bot)"
& $NssmExe set $TunnelName Start SERVICE_DEMAND_START
& $NssmExe set $TunnelName AppExit Default Restart
& $NssmExe set $TunnelName AppRestartDelay 5000
Write-Host "   OK: Tunnel service installed" -ForegroundColor Green

Write-Host ""
Write-Host ">> Installing service" -ForegroundColor Cyan
& $NssmExe install $ServiceName $PythonResolved
& $NssmExe set $ServiceName AppParameters $MainScript
& $NssmExe set $ServiceName AppDirectory $BotDir
# Unbuffered: otherwise Python holds output back and the log files stay empty for ages.
# UTF-8: otherwise emoji in log lines are written as \U0001f... escapes.
& $NssmExe set $ServiceName AppEnvironmentExtra PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
& $NssmExe set $ServiceName DisplayName "Tower of Last Chance Discord Bot"
& $NssmExe set $ServiceName Description "Tower bot - auto restarts on crash"
& $NssmExe set $ServiceName Start SERVICE_DEMAND_START
& $NssmExe set $ServiceName DependOnService MySQL96 $TunnelName
& $NssmExe set $ServiceName AppRestartDelay 5000
& $NssmExe set $ServiceName AppThrottle 10000
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppStdout ($LogDir + "\bot_stdout.log")
& $NssmExe set $ServiceName AppStderr ($LogDir + "\bot_stderr.log")
& $NssmExe set $ServiceName AppStdoutCreationDisposition 4
& $NssmExe set $ServiceName AppStderrCreationDisposition 4
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateSeconds 86400
& $NssmExe set $ServiceName AppRotateBytes 10485760
Write-Host "   OK: Service installed" -ForegroundColor Green

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Done! TowerBotService installed (manual start, not started)." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Start it from services.msc, or:"
Write-Host "  Start:  Start-Service TowerBotService   (also starts MySQL96 and TowerTunnel)"
Write-Host "  Stop:   Stop-Service TowerBotService"
Write-Host "  Status: Get-Service TowerBotService"
Write-Host "  Restart: Restart-Service TowerBotService"
Write-Host ("  Logs:   " + $LogDir + "\bot_stderr.log")
Write-Host ""
