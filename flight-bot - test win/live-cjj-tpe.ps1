param(
    [switch]$Headless
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

$VenvPython = Join-Path $RepoRoot '.venv-win\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    throw 'Run setup-and-unit-test.ps1 first. .venv-win was not found.'
}

$env:BROWSER_DEBUG_DIR = (Join-Path $RepoRoot 'artifacts\live-smoke-win')
$env:BROWSER_HEADLESS = if ($Headless) { 'true' } else { 'false' }

Write-Host 'Live Google Flights smoke test'
Write-Host '  CJJ -> TPE'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host "  Chromium headless: $($env:BROWSER_HEADLESS)"
Write-Host "  Screenshots: $($env:BROWSER_DEBUG_DIR)"
Write-Host ''

& $VenvPython 'scripts\live_smoke.py'
if ($LASTEXITCODE -ne 0) {
    throw "Live smoke failed with exit code $LASTEXITCODE. Check artifacts\live-smoke-win for screenshots."
}
