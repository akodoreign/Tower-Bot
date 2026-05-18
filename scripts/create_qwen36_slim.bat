@echo off
echo ============================================================
echo  Deprecated: qwen3.6 slim models are no longer used by this bot
echo ============================================================
echo.

echo This helper used to create qwen3.6-slim, but the supported model is now:
echo   qwen3-8b-slim:latest
echo.
echo No model will be created by this deprecated script.

echo.
echo ============================================================
echo  Setting Windows system env vars for max GPU offload
echo  (requires admin - will prompt UAC)
echo ============================================================
echo.

REM OLLAMA_GPU_OVERHEAD: reduce reserved VRAM buffer from ~500MB to 128MB
REM gives ~370MB more VRAM for model layers
powershell -Command "Start-Process powershell -Verb RunAs -ArgumentList '-Command [System.Environment]::SetEnvironmentVariable(\"OLLAMA_GPU_OVERHEAD\",\"134217728\",\"Machine\")'
" 2>nul

echo.
echo Done. Next steps:
echo  1. Restart the Ollama service (or reboot) for env vars to take effect
echo  2. Ensure .env uses: OLLAMA_MODEL=qwen3-8b-slim:latest
echo  3. Restart the bot
echo.
echo TIP: Also check your BIOS for Resizable BAR / Above 4G Decoding
echo      This doubles CPU-to-GPU bandwidth for mixed RAM/VRAM models.
echo.
pause
