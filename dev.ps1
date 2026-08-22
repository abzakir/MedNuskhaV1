# Windows equivalent of `make dev` (AGENTS.md §7).
# Backend on :8000, frontend on :3000. Ctrl-C stops both.
. (Join-Path $PSScriptRoot "_paths.ps1")

Write-Host "backend  -> http://localhost:8000  (health: /api/health)" -ForegroundColor Cyan
Write-Host "frontend -> http://localhost:3000" -ForegroundColor Cyan

$backend = Start-Process -FilePath (Join-Path $VenvDir "uvicorn.exe") `
    -ArgumentList "app.main:app","--app-dir","backend","--host","0.0.0.0","--port","8000","--reload" `
    -WorkingDirectory $Root -NoNewWindow -PassThru

try {
    Push-Location (Join-Path $Root "frontend")
    npm run dev
} finally {
    Pop-Location
    if ($backend -and -not $backend.HasExited) {
        Write-Host "`nStopping backend ..." -ForegroundColor Yellow
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }
}
