# Start the whole of MedNuskha with one command.
#
#   .\dev.ps1
#
# Opens three processes:
#   WhatsApp bridge  :3001   (its own window - the QR code appears there)
#   Backend API      :8000   (its own window - reminders and agent logs)
#   Dashboard        :3000   (this window - Ctrl-C stops everything)
#
# Closing this window, or Ctrl-C, shuts all three down.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

# ---------------------------------------------------------------- checks
$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "No Python virtualenv yet. Run .\install.ps1 first." -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "Installing dashboard dependencies (first run only)..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend"); npm install; Pop-Location
}
if (-not (Test-Path (Join-Path $root "whatsapp-bridge\node_modules"))) {
    Write-Host "Installing bridge dependencies (first run only)..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "whatsapp-bridge"); npm install; Pop-Location
}

# ---------------------------------------------------------------- env
# The backend rejects any webhook without WEBHOOK_SECRET in its path, so the
# bridge has to be told. Without this every patient reply is answered with a
# 403 and silently lost.
$envFile = Join-Path $root ".env"
$secret = ""
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*WEBHOOK_SECRET\s*=\s*(.+?)\s*$') { $secret = $Matches[1] }
    }
}
if ([string]::IsNullOrWhiteSpace($secret)) {
    Write-Host "WARNING: WEBHOOK_SECRET is not set in .env - replies will be rejected." -ForegroundColor Red
    $webhookUrl = "http://127.0.0.1:8000/webhook"
} else {
    $webhookUrl = "http://127.0.0.1:8000/webhook/$secret"
}

# `next build` and `next dev` share the .next folder and write incompatible
# things into it. If a production build was run while dev was up, the dev
# server dies with "Cannot find module ./vendor-chunks/...". BUILD_ID only
# exists after `next build`, so it is a precise signal that the cache is the
# wrong shape for dev.
$buildId = Join-Path $root "frontend\.next\BUILD_ID"
if (Test-Path $buildId) {
    Write-Host "  clearing a leftover production build from .next" -ForegroundColor DarkGray
    Remove-Item -Recurse -Force (Join-Path $root "frontend\.next") -ErrorAction SilentlyContinue
}

# Anything still listening from a previous run has to go, or the new process
# silently fails to bind and you debug the wrong thing.
foreach ($port in 3001, 8000, 3000) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        Write-Host "  freeing port $port" -ForegroundColor DarkGray
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

$started = @()

function Start-Piece([string]$title, [string]$workdir, [string]$command) {
    $script = "`$Host.UI.RawUI.WindowTitle='MedNuskha - $title'; Set-Location '$workdir'; $command"
    $proc = Start-Process powershell `
        -ArgumentList "-NoExit", "-NoProfile", "-Command", $script `
        -PassThru
    $script:started += $proc
    return $proc
}

Write-Host ""
Write-Host "Starting MedNuskha..." -ForegroundColor Cyan
Write-Host ""

# 1. bridge first - the backend checks it, and a first run needs the QR scanned
$authDir = Join-Path $root "whatsapp-bridge\auth_info"
Start-Piece "WhatsApp bridge" (Join-Path $root "whatsapp-bridge") `
    "`$env:BACKEND_WEBHOOK_URL='$webhookUrl'; node index.js" | Out-Null
Write-Host "  [1/3] WhatsApp bridge  -> http://localhost:3001/status" -ForegroundColor Green
if (-not (Test-Path $authDir)) {
    Write-Host "        First run: a QR code is printing in the bridge window." -ForegroundColor Yellow
    Write-Host "        Scan it with the SPARE phone:" -ForegroundColor Yellow
    Write-Host "        WhatsApp > Settings > Linked devices > Link a device" -ForegroundColor Yellow
}

# 2. backend
Start-Piece "Backend API" $root `
    "& '$venvPython' -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000" | Out-Null
Write-Host "  [2/3] Backend API      -> http://localhost:8000/api/health" -ForegroundColor Green

# Wait for the API before the dashboard, so the first page load is not an error.
$ready = $false
foreach ($i in 1..40) {
    Start-Sleep -Milliseconds 500
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2 | Out-Null
        $ready = $true; break
    } catch { }
}
if (-not $ready) {
    Write-Host "        Backend is slow to start - check its window for errors." -ForegroundColor Yellow
}

Write-Host "  [3/3] Dashboard        -> http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "  Open  http://localhost:3000  in your browser." -ForegroundColor Cyan
Write-Host "  Ctrl-C here stops all three." -ForegroundColor DarkGray
Write-Host ""

try {
    Push-Location (Join-Path $root "frontend")
    npm run dev
} finally {
    Pop-Location
    Write-Host ""
    Write-Host "Shutting down..." -ForegroundColor Yellow
    foreach ($proc in $started) {
        if ($proc -and -not $proc.HasExited) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
    foreach ($port in 3001, 8000) {
        $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        foreach ($conn in $conns) {
            Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "Stopped." -ForegroundColor DarkGray
}
