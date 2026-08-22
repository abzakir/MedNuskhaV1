# Windows equivalent of `make install` (AGENTS.md §7).
$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "Creating virtualenv at backend\.venv ..." -ForegroundColor Cyan
python -m venv (Join-Path $Root "backend\.venv")

$VenvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r (Join-Path $Root "backend\requirements.txt")

Write-Host "Installing frontend dependencies ..." -ForegroundColor Cyan
Push-Location (Join-Path $Root "frontend")
npm install
Pop-Location

Write-Host "Done. Run .\dev.ps1" -ForegroundColor Green
