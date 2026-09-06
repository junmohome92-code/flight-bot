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
if ($Headless) {
    throw 'The current Google acceptance probe requires a visible native Edge window. Use 02-live-cjj-tpe-visible.cmd.'
}

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONWARNINGS = 'ignore::SyntaxWarning'
try { chcp 65001 > $null } catch { }

$env:BROWSER_HEADLESS = 'false'
$env:BROWSER_TIMEOUT_MS = '60000'
$env:BROWSER_DEBUG_DIR = (Join-Path $RepoRoot 'artifacts\google-ui-win')
$env:BROWSER_PROFILE_DIR = (Join-Path $RepoRoot 'artifacts\google-profile-win')
$env:BROWSER_KEEP_OPEN_SECONDS = '8'
$env:GOOGLE_UI_SELECTION_WAIT_MS = '25000'
$env:GOOGLE_UI_DEPARTURE_CAPTURE_MS = '3500'
$env:GOOGLE_UI_PRICE_READY_WAIT_MS = '8000'
$env:GOOGLE_UI_PRICE_RELOADS = '2'
$env:ALERT_NONSTOP_ONLY = 'true'
if (-not $env:ALERT_MAX_OFFERS) {
    $env:ALERT_MAX_OFFERS = '4'
}

# The Python probe now builds the URL through the exact same production query
# builder used by scheduled/manual alerts. Never keep a second hard-coded TFS
# URL here or the acceptance/runtime implementations can drift again.
Remove-Item Env:GOOGLE_UI_SEARCH_URL -ErrorAction SilentlyContinue
Remove-Item Env:BROWSER_CHANNEL -ErrorAction SilentlyContinue
Remove-Item Env:GOOGLE_UI_CHEAPEST_URL -ErrorAction SilentlyContinue

Write-Host 'Google Flights direct-results alert acceptance'
Write-Host '  production query contract: accepted-tfs-v1'
Write-Host '  CJJ -> TPE -> CJJ'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  existing Edge startup tab reused: YES'
Write-Host '  Cheapest selected before forced refresh: YES'
Write-Host '  forced full refresh after Cheapest: 1'
Write-Host '  additional Price unavailable recovery reloads: 2 max'
Write-Host '  alert candidates: NONSTOP ONLY'
Write-Host "  alert max offers: $($env:ALERT_MAX_OFFERS) (configurable)"
Write-Host '  if fewer direct flights exist: show available rows only'
Write-Host '  Booking navigation: NO'
Write-Host '  external checkout navigation: NO'
Write-Host '  user-facing link: Google Flights search results ONLY'
Write-Host '  body-wide price fallback: NO'
Write-Host "  departure settle window: $($env:GOOGLE_UI_DEPARTURE_CAPTURE_MS) ms"
Write-Host "  selection wait: $($env:GOOGLE_UI_SELECTION_WAIT_MS) ms"
Write-Host ''

& $VenvPython 'scripts\google_results_acceptance.py'
if ($LASTEXITCODE -ne 0) {
    throw "Google UI direct-results acceptance failed with exit code $LASTEXITCODE. Check artifacts\google-ui-win."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste DIRECT GOOGLE RESULTS and SUMMARY into the next ChatGPT chat.'
