# Runs the WhatsApp bridge on its own, so you can see and scan the QR code.
#
#   .\bridge.ps1
#
# First run prints a QR. Scan it with the SPARE phone:
#   WhatsApp -> Settings -> Linked devices -> Link a device
#
# The login is saved in whatsapp-bridge\auth_info\ (gitignored), so you only
# scan once. Deleting that folder forces a fresh pairing.
$ErrorActionPreference = "Stop"
$root   = $PSScriptRoot
$bridge = Join-Path $root "whatsapp-bridge"

if (-not (Test-Path (Join-Path $bridge "node_modules"))) {
    Write-Host "Installing bridge dependencies (first run only)..." -ForegroundColor Cyan
    Push-Location $bridge; npm install; Pop-Location
}

# The backend rejects any webhook that does not carry WEBHOOK_SECRET in its
# path, so read it out of .env and build the URL. Without this every reply
# from a patient is silently answered with a 403.
$envFile = Join-Path $root ".env"
$secret  = ""
$apiBase = "http://127.0.0.1:8000"
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*WEBHOOK_SECRET\s*=\s*(.+)\s*$') { $secret = $Matches[1].Trim() }
        if ($line -match '^\s*BACKEND_API_BASE\s*=\s*(.+)\s*$') { $apiBase = $Matches[1].Trim() }
    }
}

if ([string]::IsNullOrWhiteSpace($secret)) {
    Write-Host "WARNING: WEBHOOK_SECRET is not set in .env." -ForegroundColor Red
    Write-Host "         Incoming replies will be rejected by the backend." -ForegroundColor Red
    $env:BACKEND_WEBHOOK_URL = "$apiBase/webhook"
} else {
    $env:BACKEND_WEBHOOK_URL = "$apiBase/webhook/$secret"
    Write-Host "Forwarding replies to $apiBase/webhook/<secret>" -ForegroundColor DarkGray
}

$authDir = Join-Path $bridge "auth_info"
if (Test-Path $authDir) {
    Write-Host "Existing login found - reconnecting, no QR needed." -ForegroundColor Green
} else {
    Write-Host "No login yet - a QR code will appear below." -ForegroundColor Yellow
    Write-Host "On the SPARE phone: WhatsApp > Settings > Linked devices > Link a device" -ForegroundColor Yellow
}
Write-Host ""

Push-Location $bridge
try { node index.js } finally { Pop-Location }
