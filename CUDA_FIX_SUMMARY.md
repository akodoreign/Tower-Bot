# CUDA Fix for Qwen - Action Summary

## What Was Done

✓ **Environment Variables Set:** 
- CUDA_VISIBLE_DEVICES = 0
- OLLAMA_NUM_GPU = 1
- OLLAMA_GPU_MEMORY = 0

✓ **Ollama Process Stopped**

## What You Need To Do Now

### Step 1: Restart Ollama (IMPORTANT - DO THIS NOW)

**Option A: Using Ollama App**
1. Open the Ollama application from your system
2. It will automatically detect the new CUDA environment variables
3. Ollama will start using GPU acceleration

**Option B: Command Line**
```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
```

### Step 2: Verify Qwen is Using CUDA

**Quick Test:**
```bash
ollama run qwen3:8b "Hello, how are you?"
```

**Expected Results:**
- **CPU mode:** 10-30+ seconds
- **GPU mode (CUDA):** 2-5 seconds

**Check Logs for GPU Activity:**
1. Open File Explorer
2. Navigate to: `%LOCALAPPDATA%\Ollama\logs`
3. Look for the latest log file
4. Search for lines containing:
   - "VRAM in use:"
   - "GPU device"
   - "NVIDIA"
   - "cuda"

**Example of GPU being used:**
```
VRAM in use: 6.8 GiB / 24.0 GiB
GPU device 0: NVIDIA RTX 4090 ...
```

### Step 3: Test with Discord Bot

Once Ollama is running with GPU:
1. Send a message to your Discord bot
2. Response should be immediate (2-5 seconds)
3. If still slow, check:
   - Ollama logs for GPU errors
   - GPU memory usage with: `nvidia-smi`

## Environment Variables Explained

| Variable | Value | What It Does |
|----------|-------|-------------|
| `CUDA_VISIBLE_DEVICES` | `0` | Tell CUDA to use GPU 0 |
| `OLLAMA_NUM_GPU` | `1` | Use 1 GPU for inference |
| `OLLAMA_GPU_MEMORY` | `0` | Use all available VRAM (no limit) |

## Troubleshooting

### Ollama Still Uses CPU
- [ ] Check that Ollama was restarted AFTER setting environment variables
- [ ] Verify NVIDIA driver: `nvidia-smi` in command line
- [ ] Check Ollama logs for GPU errors
- [ ] Try: `ollama pull qwen3:8b` to re-download model

### "VRAM in use" not shown in logs
- Ollama might not be detecting GPU
- Verify driver with: `nvidia-smi`
- Try restarting computer
- Check for CUDA driver conflicts

### Ollama won't start
- Open Task Manager, end any orphan Ollama processes
- Try starting Ollama application from desktop
- Check logs: `%LOCALAPPDATA%\Ollama\logs`

## Files Created

- `enable_ollama_cuda.ps1` - Automated CUDA setup script
- `QWEN_CUDA_FIX.md` - Detailed troubleshooting guide
- `CUDA_FIX_SUMMARY.md` - This file

---

**Next Step:** Restart Ollama and test! ✓
