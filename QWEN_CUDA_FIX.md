# Fixing Qwen CUDA Support in Ollama

## Problem
After switching from Mistral to Qwen, Ollama is no longer using NVIDIA CUDA acceleration and is falling back to CPU mode, causing slower inference.

## Root Cause
On Windows, Ollama requires explicit environment variables to enable GPU support. These settings may not persist across model changes or restarts.

## Solution

### Step 1: Quick Fix (Recommended)
Run the provided PowerShell script to automatically enable CUDA support:

```powershell
.\enable_ollama_cuda.ps1
```

This script will:
- ✓ Stop Ollama service
- ✓ Set required CUDA environment variables
- ✓ Persist environment variables to Windows
- ✓ Restart Ollama service with GPU enabled
- ✓ Verify connectivity

### Step 2: Verify GPU is Active
After running the script:

1. Check that Ollama is using CUDA:
   - Open Ollama logs (usually in `%LOCALAPPDATA%\Ollama\logs`)
   - Look for messages like:
     - `VRAM in use: X MiB`
     - `GPU device index: 0`
     - `MoE routing layer with GPU`

2. Run a quick test:
   ```bash
   ollama run qwen3:8b "Hello"
   ```
   - CPU mode: Takes 5-10+ seconds
   - GPU mode (CUDA): Takes 1-2 seconds

### Step 3: Verify in Discord Bot
Send a message to your bot and it should respond much faster:
- CPU: 10-30 seconds
- GPU (CUDA): 2-5 seconds

## Manual Configuration

If the script doesn't work, configure manually:

### Windows Environment Variables
Set these in System Properties → Environment Variables → User variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `OLLAMA_NUM_GPU` | `1` | Enable 1 GPU |
| `OLLAMA_GPU_MEMORY` | `0` | Use all available VRAM |
| `CUDA_VISIBLE_DEVICES` | `0` | Use GPU 0 (set to `1` for GPU 1, etc.) |

Then restart Ollama:
```powershell
net stop ollama
net start ollama
```

### For Multiple GPUs
To use GPU 1 instead of GPU 0:
```powershell
$env:CUDA_VISIBLE_DEVICES = "1"
```

To use both GPUs:
```powershell
$env:CUDA_VISIBLE_DEVICES = "0,1"
```

## Troubleshooting

### "Still using CPU"
1. Verify NVIDIA driver:
   ```
   nvidia-smi
   ```
   Should show your GPU model and CUDA version

2. Check if CUDA Toolkit is installed properly

3. Re-pull the Qwen model:
   ```
   ollama pull qwen3:8b
   ```

4. Check Ollama logs for GPU errors:
   - Windows: `%LOCALAPPDATA%\Ollama\logs\server.log`
   - Look for `failed to load` or `GPU` errors

### "Ollama won't start"
1. Try starting manually:
   ```powershell
   net start ollama
   ```

2. Check service status:
   ```powershell
   Get-Service Ollama
   ```

3. If stuck, restart and try:
   ```powershell
   net stop ollama
   Start-Sleep -Seconds 5
   net start ollama
   ```

### "Still slow even on GPU"
- Qwen 8B model is slower than Mistral
- Verify in logs that GPU is actually being used
- Check GPU memory usage with `nvidia-smi` (should show ~7GB in use)

## Performance Comparison

Expected speeds with Qwen 3:8b:

| Mode | Time per Response | VRAM Used |
|------|------------------|-----------|
| CPU (8 thread) | 10-30s | ~100 MB |
| **CUDA GPU** | **2-5s** | **~7 GB** |

## Environment Variables Reference

### Ollama CUDA Configuration

- `OLLAMA_NUM_GPU` - Number of GPUs to use (default: 1)
- `OLLAMA_GPU_MEMORY` - GPU memory in MB to use (0 = all)
- `OLLAMA_DEBUG` - Set to `1` for verbose logging
- `OLLAMA_HOST` - Server address (default: localhost:11434)

### CUDA Configuration

- `CUDA_VISIBLE_DEVICES` - Which GPU(s) to expose (e.g., "0" or "0,1")
- `CUDA_DEVICE_ORDER` - Device priority (e.g., "PCI_BUS_ID")

## Next Steps

1. Run `.\enable_ollama_cuda.ps1`
2. Wait 10 seconds for Ollama to start
3. Test with `/chat` command in Discord
4. If still slow, check `/logs/worklog_*.md` for any issues
5. If GPU still not detected, run `nvidia-smi` to verify driver

---

**Last Updated:** April 3, 2026
**Affected Model:** Qwen 3:8b
**Related Issue:** CUDA acceleration not enabled after model switch
