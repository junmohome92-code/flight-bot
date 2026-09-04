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

$env:BROWSER_HEADLESS = if ($Headless) { 'true' } else { 'false' }
$env:BROWSER_TIMEOUT_MS = '60000'
$env:BROWSER_DEBUG_DIR = (Join-Path $RepoRoot 'artifacts\google-ui-win')
$env:BROWSER_PROFILE_DIR = (Join-Path $RepoRoot 'artifacts\google-profile-win')
$env:BROWSER_KEEP_OPEN_SECONDS = if ($Headless) { '0' } else { '8' }

# Do not use the personal Edge/Chrome profile. The probe uses its own persistent
# profile so Google sees a normal browser session over repeated checks without
# risking the user's real browser data.
Remove-Item Env:BROWSER_CHANNEL -ErrorAction SilentlyContinue

Write-Host 'Google Flights real UI probe'
Write-Host '  CJJ -> TPE'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  direct tfs URL: NO'
Write-Host '  fast-flights parser: NO'
Write-Host '  Fli direct API: NO'
Write-Host '  persistent browser profile: YES'
Write-Host "  headless: $($env:BROWSER_HEADLESS)"
Write-Host ''

& $VenvPython 'scripts\google_ui_probe.py'
if ($LASTEXITCODE -ne 0) {
    throw "Google UI live probe failed with exit code $LASTEXITCODE. Check artifacts\google-ui-win."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste the price candidate list and SUMMARY output into the next ChatGPT chat.'
