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
$bridge = Join-Path $PSScriptRoot "whatsapp-bridge"

if (-not (Test-Path (Join-Path $bridge "node_modules"))) {
    Write-Host "Installing bridge dependencies (first run only)..." -ForegroundColor Cyan
    Push-Location $bridge; npm install; Pop-Location
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
