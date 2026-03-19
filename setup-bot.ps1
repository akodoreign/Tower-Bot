# ================================
# ChatGPT Discord Bot setup script
# - Fix Python 3.11 Scripts PATH
# - Install requirements with Python 3.11
# ================================

Write-Host "== ChatGPT Discord Bot setup starting ==" -ForegroundColor Cyan

# 1) Ensure Python 3.11 Scripts path is in PATH (current session)
$pyScripts = "C:\Program Files\Python311\Scripts"

if (-not ($env:Path.Split(';') -contains $pyScripts)) {
    Write-Host "Adding '$pyScripts' to PATH for this session..." -ForegroundColor Yellow
    $env:Path += ";$pyScripts"
} else {
    Write-Host "'$pyScripts' already in PATH for this session." -ForegroundColor Green
}

# OPTIONAL: Persist the PATH fix system-wide (uncomment if you want this)
# NOTE: Run PowerShell as Administrator if you un-comment this.
# [System.Environment]::SetEnvironmentVariable(
#     'Path',
#     ($env:Path + ";$pyScripts"),
#     [System.EnvironmentVariableTarget]::Machine
# )

# 2) Verify Python 3.11 is available
Write-Host "Checking Python 3.11..." -ForegroundColor Cyan
py -3.11 --version

# 3) Upgrade pip (optional but nice)
Write-Host "Upgrading pip for Python 3.11 (optional step)..." -ForegroundColor Cyan
py -3.11 -m pip install --upgrade pip

# 4) Install requirements with Python 3.11
Write-Host "Installing requirements from requirements.txt using Python 3.11..." -ForegroundColor Cyan
py -3.11 -m pip install -r requirements.txt

Write-Host "`n    py -3.11 main.py`n" -ForegroundColor Yellow

