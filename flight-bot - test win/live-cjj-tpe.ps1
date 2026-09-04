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

# PyPI currently publishes flights only through 0.9.0, while the Google
# round-trip expansion / GetBookingResults code under test lives in this
# newer upstream commit. Pin the exact GitHub source ZIP so the test is
# reproducible and does not require Git to be installed on Windows.
$FliCommit = '121d34fea056dc513258958c4262cb5a4cc033c1'
$FliSource = "https://github.com/punitarani/fli/archive/$FliCommit.zip"

Write-Host 'Fli direct Google Flights service probe'
Write-Host '  CJJ -> TPE'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  sort: CHEAPEST'
Write-Host '  round-trip expansion + booking verification'
Write-Host "  fli source commit: $($FliCommit.Substring(0, 12))"
Write-Host ''

Write-Host '[1/2] Installing/confirming pinned Fli GitHub source ...'
& $VenvPython -m pip install --disable-pip-version-check --quiet --upgrade $FliSource
if ($LASTEXITCODE -ne 0) {
    throw "Installing pinned Fli source failed with exit code $LASTEXITCODE."
}

# Fail immediately if the installed source does not expose the APIs required by
# this probe. This avoids mistaking an older PyPI package for the pinned build.
& $VenvPython -c "from fli.search import SearchFlights; assert hasattr(SearchFlights, 'get_booking_options'); print('Fli booking API: OK')"
if ($LASTEXITCODE -ne 0) {
    throw "Pinned Fli API verification failed with exit code $LASTEXITCODE."
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
