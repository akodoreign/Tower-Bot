$ServiceName = "TowerBotService"
$BotDir = "C:\Users\akodoreign\Desktop\chatGPT-discord-bot"
$LogDir = $BotDir + "\logs"
$NssmExe = $BotDir + "\nssm.exe"
$MainScript = $BotDir + "\main.py"

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
Write-Host ">> Resolving Python 3.11 path" -ForegroundColor Cyan
$PythonResolved = & py -3.11 -c "import sys; print(sys.executable)" 2>$null
if (-not $PythonResolved -or -not (Test-Path $PythonResolved)) {
    Write-Host "   FAIL: Python 3.11 not found" -ForegroundColor Red
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
Write-Host ">> Installing service" -ForegroundColor Cyan
& $NssmExe install $ServiceName $PythonResolved
& $NssmExe set $ServiceName AppParameters $MainScript
& $NssmExe set $ServiceName AppDirectory $BotDir
& $NssmExe set $ServiceName DisplayName "Tower of Last Chance Discord Bot"
& $NssmExe set $ServiceName Description "Tower bot - auto restarts on crash"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppRestartDelay 5000
& $NssmExe set $ServiceName AppThrottle 10000
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppStdout ($LogDir + "\bot_stdout.log")
& $NssmExe set $ServiceName AppStderr ($LogDir + "\bot_stderr.log")
& $NssmExe set $ServiceName AppStdoutCreationDisposition Append
& $NssmExe set $ServiceName AppStderrCreationDisposition Append
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateSeconds 86400
& $NssmExe set $ServiceName AppRotateBytes 10485760
Write-Host "   OK: Service installed" -ForegroundColor Green

Write-Host ""
Write-Host ">> Starting service" -ForegroundColor Cyan
& $NssmExe start $ServiceName
Start-Sleep -Seconds 3
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "   OK: Service is RUNNING" -ForegroundColor Green
} else {
    Write-Host "   Service did not start - check logs" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Done! TowerBotService installed." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Start:  Start-Service TowerBotService"
Write-Host "  Stop:   Stop-Service TowerBotService"
Write-Host "  Status: Get-Service TowerBotService"
Write-Host "  Restart: Restart-Service TowerBotService"
Write-Host ("  Logs:   " + $LogDir + "\bot_stderr.log")
Write-Host ""
