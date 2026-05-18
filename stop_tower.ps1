# ============================================
# TOWER OF LAST CHANCE — Clean Shutdown
# Run as: .\stop_tower.ps1
# ============================================

Write-Host ""
Write-Host "Stopping Tower of Last Chance..." -ForegroundColor Yellow
Write-Host ""

# Stop bot
Write-Host "  Stopping bot..." -ForegroundColor Gray
Get-Process -Name "python" -ErrorAction SilentlyContinue | Stop-Process -Force 2>$null

# Stop Ollama
Write-Host "  Stopping Ollama..." -ForegroundColor Gray
taskkill /f /im ollama.exe 2>$null | Out-Null

Start-Sleep 2

Write-Host ""
Write-Host "All services stopped." -ForegroundColor Green
Write-Host "  A1111 still running (background process) — kill manually if needed:" -ForegroundColor Gray
Write-Host "    Get-Process python | Where-Object {`$_.CommandLine -like '*launch.py*'} | Stop-Process" -ForegroundColor White
Write-Host ""
