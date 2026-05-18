param(
    [string]$A1111Root = "C:\ai\StabilityMatrix\Data\Packages\Stable Diffusion WebUI\models",
    [string]$SharedRoot = "C:\ai\StabilityMatrix\Data\Models"
)

$ErrorActionPreference = "Stop"

function Ensure-Directory([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path | Out-Null
    }
}

function Link-Or-Copy([string]$Source, [string]$Dest) {
    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Host "missing source: $Source"
        return
    }
    if (Test-Path -LiteralPath $Dest) {
        Write-Host "exists: $Dest"
        return
    }

    Ensure-Directory (Split-Path -Parent $Dest)
    try {
        New-Item -ItemType HardLink -Path $Dest -Target $Source | Out-Null
        Write-Host "linked: $Dest"
    } catch {
        Copy-Item -LiteralPath $Source -Destination $Dest
        Write-Host "copied: $Dest"
    }
}

$checkpointDir = Join-Path $A1111Root "Stable-diffusion"
$loraDir = Join-Path $A1111Root "Lora"
$vaeDir = Join-Path $A1111Root "VAE"

Ensure-Directory $checkpointDir
Ensure-Directory $loraDir

$fluxCheckpointSource = Join-Path $vaeDir "flux1-dev-fp8.safetensors"
if (-not (Test-Path -LiteralPath $fluxCheckpointSource)) {
    $fluxCheckpointSource = Join-Path $SharedRoot "VAE\flux1-dev-fp8.safetensors"
}
Link-Or-Copy $fluxCheckpointSource (Join-Path $checkpointDir "flux1-dev-fp8.safetensors")

$sdxlMapcraftSource = Join-Path $checkpointDir "mapcraft_sdxl_v1.safetensors"
if (-not (Test-Path -LiteralPath $sdxlMapcraftSource)) {
    $sdxlMapcraftSource = Join-Path $SharedRoot "Lora\mapcraft_sdxl_v1.safetensors"
}
Link-Or-Copy $sdxlMapcraftSource (Join-Path $loraDir "mapcraft_sdxl_v1.safetensors")

$fluxMapcraftSource = Join-Path $SharedRoot "Lora\mapcraft_flux_v2.safetensors"
if (-not (Test-Path -LiteralPath $fluxMapcraftSource)) {
    $fluxMapcraftSource = Join-Path $loraDir "mapcraft_flux_v2.safetensors"
}
Link-Or-Copy $fluxMapcraftSource (Join-Path $loraDir "mapcraft_flux_v2.safetensors")

Write-Host "MapCraft model prep complete."
