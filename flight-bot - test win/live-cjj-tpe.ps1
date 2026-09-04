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

Write-Host 'Fli direct Google Flights service probe'
Write-Host '  CJJ -> TPE'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  sort: CHEAPEST'
Write-Host '  round-trip expansion + booking verification'
Write-Host ''

Write-Host '[1/2] Installing/confirming flights==0.10.0 ...'
& $VenvPython -m pip install --disable-pip-version-check --quiet 'flights==0.10.0'
if ($LASTEXITCODE -ne 0) {
    throw "Installing flights==0.10.0 failed with exit code $LASTEXITCODE."
}

Write-Host '[2/2] Querying Google Flights internal service ...'
Write-Host ''
& $VenvPython 'scripts\fli_live_probe.py'
if ($LASTEXITCODE -ne 0) {
    throw "Fli live probe failed with exit code $LASTEXITCODE."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste the itinerary list and SUMMARY output back into ChatGPT.'
