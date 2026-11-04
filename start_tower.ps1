# ============================================
# TOWER OF LAST CHANCE - Full Stack Startup
# Run as: .\start_tower.ps1
#
# Ollama (text) and ComfyUI (images) share the one GPU; the bot's GPU queue
# decides which of them holds VRAM, so nothing is pre-loaded here.
# ComfyUI runs headless from the "ComfyUI Headless" scheduled task.
# The mission dashboard runs inside the bot (main.py) on DASHBOARD_PORT.
# ============================================

$BotDir    = $PSScriptRoot
$Python    = "$BotDir\.venv\Scripts\python.exe"
$LogDir    = "$BotDir\logs"
$ComfyUrl  = "http://127.0.0.1:8188"
$ComfyTask = "ComfyUI Headless"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Get-BotProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*main.py*" -and ($_.ExecutablePath -eq $Python -or $_.CommandLine -like "*chatGPT-discord-bot*") }
}

function Test-Url($Url) {
    try { Invoke-RestMethod -Uri $Url -TimeoutSec 5 | Out-Null; $true } catch { $false }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TOWER OF LAST CHANCE - Starting Up"  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------
# 1. STOP A RUNNING BOT (only the bot - ComfyUI is Python too)
# ------------------------------------------
Write-Host "[1/5] Stopping a running bot..." -ForegroundColor Yellow
Get-BotProcess | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep 2
Write-Host "  Done." -ForegroundColor Green

# ------------------------------------------
# 2. OLLAMA
# ------------------------------------------
Write-Host "[2/5] Ollama..." -ForegroundColor Yellow
# The "Ollama Headless" task (C:\AI\logwrap\start-ollama.ps1) sets keep-alive, turns flash
# attention off (it crashes on the RTX 5070) and logs to C:\AI\logs\ollama.
if (-not (Test-Url "http://localhost:11434/api/tags")) {
    Start-ScheduledTask "Ollama Headless"
    for ($i = 0; $i -lt 20 -and -not (Test-Url "http://localhost:11434/api/tags"); $i++) { Start-Sleep 1 }
}
if (Test-Url "http://localhost:11434/api/tags") {
    Write-Host "  Ollama is up." -ForegroundColor Green
} else {
    Write-Host "  WARNING: Ollama not responding" -ForegroundColor Red
}

# ------------------------------------------
# 3. COMFYUI (headless scheduled task)
# ------------------------------------------
Write-Host "[3/5] ComfyUI..." -ForegroundColor Yellow
if (-not (Test-Url "$ComfyUrl/system_stats")) {
    Start-ScheduledTask -TaskName $ComfyTask -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 24 -and -not (Test-Url "$ComfyUrl/system_stats"); $i++) { Start-Sleep 5 }
}
if (Test-Url "$ComfyUrl/system_stats") {
    Write-Host "  ComfyUI is up." -ForegroundColor Green
} else {
    Write-Host "  ComfyUI still starting - the bot waits for it on its own." -ForegroundColor Yellow
}

# ------------------------------------------
# 4. CLOUDFLARE TUNNEL (public dashboard)
# ------------------------------------------
Write-Host "[4/5] Cloudflare tunnel..." -ForegroundColor Yellow
if (Get-Service cloudflared -ErrorAction SilentlyContinue | Where-Object Status -eq Running) {
    Write-Host "  Tunnel service running." -ForegroundColor Green
} elseif (Get-Process cloudflared -ErrorAction SilentlyContinue) {
    Write-Host "  Tunnel already running." -ForegroundColor Green
} elseif (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    Start-Process "cloudflared" -ArgumentList "tunnel run" -WindowStyle Hidden
    Write-Host "  Tunnel started." -ForegroundColor Green
} else {
    Write-Host "  cloudflared not installed - dashboard is local only." -ForegroundColor Yellow
}

# ------------------------------------------
# 5. THE BOT (+ dashboard thread)
# ------------------------------------------
Write-Host "[5/5] Starting Tower Bot..." -ForegroundColor Yellow
Start-Process $Python -ArgumentList "main.py" -WorkingDirectory $BotDir -WindowStyle Hidden `
    -RedirectStandardError "$LogDir\bot_stderr.log"
Start-Sleep 5

$botProc = Get-BotProcess
if ($botProc) {
    Write-Host "  Bot:     RUNNING (PID $($botProc.ProcessId -join ', '))" -ForegroundColor Green
} else {
    Write-Host "  Bot:     NOT STARTED (check logs\bot_stderr.log)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Watch bot logs:" -ForegroundColor Gray
Write-Host "  Get-Content .\logs\bot_stderr.log -Tail 20 -Wait" -ForegroundColor White
Write-Host ""
