# Shared path resolution for the Windows shims. Dot-sourced, not run directly.
$ErrorActionPreference = "Stop"
$Root       = $PSScriptRoot
$VenvPython = Join-Path $Root "backend\.venv\Scripts\python.exe"
$VenvDir    = Join-Path $Root "backend\.venv\Scripts"

if (-not (Test-Path $VenvPython)) {
    Write-Host "No virtualenv at backend\.venv - run .\install.ps1 first." -ForegroundColor Yellow
    exit 1
}
