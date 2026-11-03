# ============================================
# TOWER OF LAST CHANCE - Clean Shutdown
# Run as: .\stop_tower.ps1
#
# Stops only the bot. Ollama and the headless ComfyUI are shared with other
# tools on this PC, so they keep running.
# ============================================

$Python = "$PSScriptRoot\.venv\Scripts\python.exe"

Write-Host ""
Write-Host "Stopping Tower of Last Chance..." -ForegroundColor Yellow

Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like "*main.py*" -and ($_.ExecutablePath -eq $Python -or $_.CommandLine -like "*chatGPT-discord-bot*") } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Sleep 2
Write-Host "Bot stopped. Ollama and ComfyUI are still running." -ForegroundColor Green
Write-Host ""
