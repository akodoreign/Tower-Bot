# Installs Tower Control: an always-on page (port 5050) to start/stop the bot and
# open Prompt Studio, so the bot can stay off between sessions.
# Run in an Administrator PowerShell:
#   powershell -ExecutionPolicy Bypass -File install_control_panel.ps1
$ServiceName = "TowerControl"
$BotDir = $PSScriptRoot
$LogDir = $BotDir + "\logs"
$NssmExe = $BotDir + "\nssm.exe"
$Server = $BotDir + "\control_panel\server.py"
$Python = $BotDir + "\.venv\Scripts\python.exe"
$Port = 5050
$RuleName = "Tower Control (home network)"

Write-Host ""
Write-Host ">> Checking administrator privileges" -ForegroundColor Cyan
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "   FAIL: Re-run as Administrator" -ForegroundColor Red
    exit 1
}
foreach ($p in $NssmExe, $Server, $Python) {
    if (-not (Test-Path $p)) {
        Write-Host "   FAIL: missing $p" -ForegroundColor Red
        exit 1
    }
}
Write-Host "   OK" -ForegroundColor Green

Write-Host ""
Write-Host ">> Installing the $ServiceName service (auto start, LocalSystem)" -ForegroundColor Cyan
if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    & $NssmExe stop $ServiceName | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
}
& $NssmExe install $ServiceName $Python
& $NssmExe set $ServiceName AppParameters $Server
& $NssmExe set $ServiceName AppDirectory $BotDir
& $NssmExe set $ServiceName AppEnvironmentExtra PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
& $NssmExe set $ServiceName DisplayName "Tower Control (bot start/stop page)"
& $NssmExe set $ServiceName Description "Home-network page on port $Port to start/stop TowerBotService and open Prompt Studio"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 5000
& $NssmExe set $ServiceName AppStdout ($LogDir + "\control_stdout.log")
& $NssmExe set $ServiceName AppStderr ($LogDir + "\control_stderr.log")
& $NssmExe set $ServiceName AppRotateFiles 1
& $NssmExe set $ServiceName AppRotateBytes 1048576
Write-Host "   OK" -ForegroundColor Green

Write-Host ""
Write-Host ">> Firewall: port $Port from 192.168.x.x on Wi-Fi only" -ForegroundColor Cyan
Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress 192.168.0.0/16 -InterfaceAlias "Wi-Fi" -Profile Any | Out-Null
Write-Host "   OK" -ForegroundColor Green

Write-Host ""
Write-Host ">> Starting $ServiceName" -ForegroundColor Cyan
Start-Service $ServiceName
Start-Sleep 4
Get-Service $ServiceName | Format-Table Name, Status
try {
    $code = (Invoke-WebRequest "http://127.0.0.1:$Port/api/status" -UseBasicParsing -TimeoutSec 10).StatusCode
    Write-Host "   Tower Control answers: $code" -ForegroundColor Green
} catch {
    Write-Host "   Tower Control not answering yet: $($_.Exception.Message) (see logs\control_stderr.log)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  On this PC:   http://localhost:$Port/"
Write-Host "  On your Wi-Fi: http://192.168.68.61:$Port/"
Write-Host "  TowerBotService stays Manual: after a reboot the bot is off until you press Start."
Write-Host ""
Write-Host "Done. Tell Claude 'control installed'." -ForegroundColor Green
