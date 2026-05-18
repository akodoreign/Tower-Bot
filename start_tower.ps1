# ============================================
# TOWER OF LAST CHANCE — Full Stack Startup
# Run as: .\start_tower.ps1
# Or add to Task Scheduler for auto-start on boot
# ============================================

$BotDir   = "C:\Users\akodoreign\Desktop\chatGPT-discord-bot"
$A1111Dir = "C:\AI\StabilityMatrix\Data\Packages\Stable Diffusion WebUI"
$LogDir   = "$BotDir\logs"

# Ensure logs directory exists
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  TOWER OF LAST CHANCE — Starting Up"  -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ------------------------------------------
# 1. STOP EVERYTHING CLEANLY
# ------------------------------------------
Write-Host "[1/6] Stopping existing processes..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue | Stop-Process -Force 2>$null
taskkill /f /im ollama.exe 2>$null | Out-Null

# Remove broken NSSM A1111 service if it exists
$nssm = "$BotDir\nssm.exe"
if (Test-Path $nssm) {
    & $nssm stop A1111 2>$null | Out-Null
    & $nssm remove A1111 confirm 2>$null | Out-Null
}
Start-Sleep 3
Write-Host "  Done." -ForegroundColor Green

# ------------------------------------------
# 2. START OLLAMA
# ------------------------------------------
Write-Host "[2/6] Starting Ollama..." -ForegroundColor Yellow
# OLLAMA_FLASH_ATTENTION and OLLAMA_KEEP_ALIVE are real Ollama server env vars.
# OLLAMA_NUM_CTX / OLLAMA_NUM_GPU are passed per-request in options{}, not server env vars.
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KEEP_ALIVE = "30m"
[System.Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[System.Environment]::SetEnvironmentVariable("OLLAMA_KEEP_ALIVE", "30m", "User")
Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep 5

# Verify
try {
    $response = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10
    $models = ($response.models | ForEach-Object { $_.name }) -join ", "
    Write-Host "  Ollama is up. Models: $models" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Ollama not responding yet" -ForegroundColor Red
}

# ------------------------------------------
# 3. WARM UP QWEN3 (force GPU load with 32K context, uses all VRAM via ZBAR)
# ------------------------------------------
Write-Host "[3/6] Loading qwen3:8b onto GPU (32K ctx, ZBAR extended VRAM)..." -ForegroundColor Yellow
$body = @{
    model="qwen3:8b"
    messages=@(@{role="user"; content="hi"})
    stream=$false
    options=@{num_gpu=99; num_ctx=32768; num_predict=8}
} | ConvertTo-Json -Depth 5
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/chat" -Method Post -Body $body -ContentType "application/json" -TimeoutSec 120 | Out-Null
    Write-Host "  qwen3:8b loaded onto GPU." -ForegroundColor Green
} catch {
    Write-Host "  Warmup timed out — will load on first use." -ForegroundColor Yellow
}

# Show GPU allocation
Write-Host "  GPU status:" -ForegroundColor Cyan
ollama ps

# ------------------------------------------
# 4. START A1111 (via scheduled task script)
# ------------------------------------------
Write-Host "[4/6] Starting A1111 (headless API)..." -ForegroundColor Yellow
$A1111Script = "C:\AI\StabilityMatrix\Logs\start_a1111.ps1"

# Check if A1111 is already running
$a1111Already = $false
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:7860/sdapi/v1/sd-models" -TimeoutSec 5 | Out-Null
    Write-Host "  A1111 already running!" -ForegroundColor Green
    $a1111Already = $true
} catch {}

if (-not $a1111Already) {
    if (Test-Path $A1111Script) {
        Start-Process "powershell.exe" -ArgumentList "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$A1111Script`"" -WindowStyle Hidden
        Write-Host "  A1111 launch script started." -ForegroundColor Gray

        # Wait for A1111 API to be ready (can take 30-90s to load model)
        Write-Host "  Waiting for A1111 API..." -ForegroundColor Gray
        $a1111Ready = $false
        for ($i = 0; $i -lt 24; $i++) {
            try {
                Invoke-RestMethod -Uri "http://127.0.0.1:7860/sdapi/v1/sd-models" -TimeoutSec 5 | Out-Null
                Write-Host "  A1111 API is ready!" -ForegroundColor Green
                $a1111Ready = $true
                break
            } catch {
                Write-Host "    Waiting... ($($i * 5)s)" -ForegroundColor Gray
                Start-Sleep 5
            }
        }
        if (-not $a1111Ready) {
            Write-Host "  A1111 still loading — bot will retry on its own." -ForegroundColor Yellow
        }
    } else {
        Write-Host "  A1111 script not found at $A1111Script" -ForegroundColor Red
        Write-Host "  Start it manually or update the path in this script." -ForegroundColor Gray
    }
}

# ------------------------------------------
# 5. START THE BOT
# ------------------------------------------
Write-Host "[5/7] Starting Tower Bot..." -ForegroundColor Yellow
Set-Location $BotDir
Start-Process "python" -ArgumentList "main.py" -RedirectStandardError "$LogDir\bot_stderr.log"
Start-Sleep 3

# ------------------------------------------
# 6. START DASHBOARD (Flask)
# ------------------------------------------
# Ensure firewall allows port 5000 inbound
$fwRule = Get-NetFirewallRule -DisplayName "Tower Dashboard" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    New-NetFirewallRule -DisplayName "Tower Dashboard" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 5000 | Out-Null
    Write-Host "  Firewall: port 5000 opened." -ForegroundColor Green
}
Write-Host "[6/7] Starting Mission Dashboard..." -ForegroundColor Yellow
Start-Process "python" -ArgumentList "-m flask --app Webpage/app.py run --host 0.0.0.0 --port 5000" -WorkingDirectory $BotDir -RedirectStandardError "$LogDir\dashboard_stderr.log" -WindowStyle Hidden
Start-Sleep 2
try {
    Invoke-RestMethod -Uri "http://localhost:5000/api/status" -TimeoutSec 5 | Out-Null
    Write-Host "  Dashboard: RUNNING at http://localhost:5000" -ForegroundColor Green
} catch {
    Write-Host "  Dashboard: starting (check logs\dashboard_stderr.log)" -ForegroundColor Yellow
}

# ------------------------------------------
# 7. VERIFY EVERYTHING
# ------------------------------------------
Write-Host "[7/7] Verifying..." -ForegroundColor Yellow

# Ollama
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
    Write-Host "  Ollama:  RUNNING" -ForegroundColor Green
} catch {
    Write-Host "  Ollama:  DOWN" -ForegroundColor Red
}

# A1111
try {
    Invoke-RestMethod -Uri "http://127.0.0.1:7860/sdapi/v1/sd-models" -TimeoutSec 5 | Out-Null
    Write-Host "  A1111:   RUNNING" -ForegroundColor Green
} catch {
    Write-Host "  A1111:   LOADING (check logs\a1111_stderr.log)" -ForegroundColor Yellow
}

# Bot
Start-Sleep 2
$botProc = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($botProc) {
    Write-Host "  Bot:     RUNNING (PID $($botProc.Id))" -ForegroundColor Green
} else {
    Write-Host "  Bot:     NOT STARTED (check logs\bot_stderr.log)" -ForegroundColor Red
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  ALL SYSTEMS GO" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Watch bot logs:" -ForegroundColor Gray
Write-Host "  Get-Content .\logs\bot_stderr.log -Tail 20 -Wait" -ForegroundColor White
Write-Host ""
Write-Host "Watch A1111 logs:" -ForegroundColor Gray
Write-Host "  Get-Content .\logs\a1111_stderr.log -Tail 20 -Wait" -ForegroundColor White
Write-Host ""
