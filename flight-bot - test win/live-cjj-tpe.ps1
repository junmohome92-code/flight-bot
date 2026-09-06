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
try { chcp 65001 > $null } catch { }

$env:BROWSER_HEADLESS = 'false'
$env:BROWSER_TIMEOUT_MS = '60000'
$env:BROWSER_DEBUG_DIR = (Join-Path $RepoRoot 'artifacts\google-ui-win')
$env:BROWSER_PROFILE_DIR = (Join-Path $RepoRoot 'artifacts\google-profile-win')
$env:BROWSER_KEEP_OPEN_SECONDS = '8'
$env:GOOGLE_UI_SELECTION_WAIT_MS = '25000'
$env:GOOGLE_UI_BOOKING_WAIT_MS = '15000'
$env:GOOGLE_UI_DEPARTURE_CAPTURE_MS = '3500'
$env:GOOGLE_UI_RETURN_CAPTURE_MS = '900'

$env:GOOGLE_UI_SEARCH_URL = 'https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ&hl=en&gl=kr&curr=KRW'

Remove-Item Env:BROWSER_CHANNEL -ErrorAction SilentlyContinue
Remove-Item Env:GOOGLE_UI_CHEAPEST_URL -ErrorAction SilentlyContinue

Write-Host 'Google Flights navigation-safe Cheapest + transient Booking probe'
Write-Host '  CJJ -> TPE -> CJJ'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  observer active before Cheapest click: YES'
Write-Host '  text-node mutation capture: YES'
Write-Host '  explicit Cheapest/최저가 click: YES'
Write-Host '  actual pointer-event boundary: YES'
Write-Host '  delayed selected-state cannot discard post-click transient rows: YES'
Write-Host '  fresh post-click control re-query: YES'
Write-Host '  strong selected-state evidence: aria-selected/pressed/checked/current/data-state'
Write-Host '  candidate + advertised stability gate: YES'
Write-Host '  Returning full-navigation capture: YES'
Write-Host '  stale coordinate click: NO'
Write-Host '  Booking marker required: YES'
Write-Host '  external seller checkout verification: NO'
Write-Host '  body-wide price fallback: NO'
Write-Host "  departure settle window: $($env:GOOGLE_UI_DEPARTURE_CAPTURE_MS) ms"
Write-Host "  return settle window: $($env:GOOGLE_UI_RETURN_CAPTURE_MS) ms"
Write-Host "  selection wait: $($env:GOOGLE_UI_SELECTION_WAIT_MS) ms"
Write-Host "  booking wait: $($env:GOOGLE_UI_BOOKING_WAIT_MS) ms"
Write-Host ''

& $VenvPython 'scripts\google_booking_pointer_probe_v6.py'
if ($LASTEXITCODE -ne 0) {
    throw "Google UI navigation-safe booking probe failed with exit code $LASTEXITCODE. Check artifacts\google-ui-win."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste the Cheapest/departure/return/Booking output and SUMMARY into the next ChatGPT chat.'
