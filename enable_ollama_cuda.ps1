# Enable NVIDIA CUDA support for Ollama on Windows
# Run this script to restart Ollama with GPU acceleration enabled

Write-Host "[*] Enabling NVIDIA CUDA support for Ollama..." -ForegroundColor Green

# Stop any running Ollama instance
Write-Host "[*] Stopping Ollama service..." -ForegroundColor Yellow
Stop-Service -Name Ollama -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Set environment variables for CUDA support
$env:CUDA_VISIBLE_DEVICES = "0"      # Use GPU 0 (change if you have multiple GPUs)
$env:OLLAMA_NUM_GPU = "1"             # Use 1 GPU
$env:OLLAMA_GPU_MEMORY = "0"          # Use all available VRAM (0 = unlimited)

# Add to permanent system environment (requires admin)
Write-Host "`n[*] Setting permanent environment variables..." -ForegroundColor Yellow
try {
    [Environment]::SetEnvironmentVariable('CUDA_VISIBLE_DEVICES', '0', [EnvironmentVariableTarget]::User)
    [Environment]::SetEnvironmentVariable('OLLAMA_NUM_GPU', '1', [EnvironmentVariableTarget]::User)
    [Environment]::SetEnvironmentVariable('OLLAMA_GPU_MEMORY', '0', [EnvironmentVariableTarget]::User)
    Write-Host "[OK] Environment variables set for current user" -ForegroundColor Green
}
catch {
    Write-Host "[!] Could not set system environment variables (may need admin)" -ForegroundColor Yellow
}

# Start Ollama service
Write-Host "`n[*] Starting Ollama service with CUDA enabled..." -ForegroundColor Yellow
Start-Service -Name Ollama
Start-Sleep -Seconds 3

# Verify Ollama is running
Write-Host "`n[*] Verifying Ollama connection..." -ForegroundColor Cyan
try {
    $response = (curl -s http://localhost:11434/api/tags 2>$null)
    if ($response) {
        Write-Host "[OK] Ollama is running and responding" -ForegroundColor Green
        Write-Host "`n[*] Current models loaded:" -ForegroundColor Cyan
        $models = $response | ConvertFrom-Json -ErrorAction SilentlyContinue
        if ($models.models) {
            $models.models | ForEach-Object { Write-Host "     - $($_.name)" }
        }
    }
}
catch {
    Write-Host "[!] Could not connect to Ollama. Service may not be running." -ForegroundColor Red
    Write-Host "     Try: net start ollama" -ForegroundColor Yellow
}

Write-Host "`n[*] To verify Qwen is using CUDA, check for 'GPU' in Ollama logs:" -ForegroundColor Cyan
Write-Host "     - Ollama logs are in: %LOCALAPPDATA%\Ollama\logs" -ForegroundColor Gray
Write-Host "     - Look for lines like: 'MoE routing layer with GPU' or 'VRAM in use'" -ForegroundColor Gray

Write-Host "`n[*] If Qwen still runs on CPU:" -ForegroundColor Yellow
Write-Host "     1. Verify NVIDIA driver is installed (nvidia-smi)" -ForegroundColor Gray
Write-Host "     2. Check Ollama GPU settings in system settings" -ForegroundColor Gray
Write-Host "     3. Try pulling Qwen again: ollama pull qwen3:8b" -ForegroundColor Gray
