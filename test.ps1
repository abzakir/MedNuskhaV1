# Windows equivalent of `make test` (AGENTS.md §7).
. (Join-Path $PSScriptRoot "_paths.ps1")
Push-Location (Join-Path $Root "backend")
try { & $VenvPython -m pytest -q } finally { Pop-Location }
