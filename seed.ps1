# Windows equivalent of `make seed` (AGENTS.md §7).
. (Join-Path $PSScriptRoot "_paths.ps1")
& $VenvPython (Join-Path $Root "scripts\seed_demo.py")
