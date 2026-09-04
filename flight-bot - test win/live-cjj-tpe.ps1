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

Write-Host 'Direct Google Flights data probe'
Write-Host '  CJJ -> TPE'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  separate ticket / self-transfer: allowed'
Write-Host ''
Write-Host 'This test does NOT use the Playwright DOM parser.'
Write-Host 'It compares round-trip pricing with two independent one-way searches.'
Write-Host ''

& $VenvPython 'scripts\fast_flights_probe.py'
if ($LASTEXITCODE -ne 0) {
    throw "Direct fast-flights probe failed with exit code $LASTEXITCODE."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste the ROUND TRIP / ONE WAY / SUMMARY output back into ChatGPT.'
