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

# Keep Korean/₩ diagnostics readable in Windows console.
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
try { chcp 65001 > $null } catch { }

$env:BROWSER_HEADLESS = if ($Headless) { 'true' } else { 'false' }
$env:BROWSER_TIMEOUT_MS = '60000'
$env:BROWSER_DEBUG_DIR = (Join-Path $RepoRoot 'artifacts\google-ui-win')
$env:BROWSER_PROFILE_DIR = (Join-Path $RepoRoot 'artifacts\google-profile-win')
$env:BROWSER_KEEP_OPEN_SECONDS = if ($Headless) { '0' } else { '8' }
$env:GOOGLE_UI_SELECTION_WAIT_MS = '20000'
$env:GOOGLE_UI_BOOKING_WAIT_MS = '15000'
$env:GOOGLE_UI_DEPARTURE_CAPTURE_MS = '1500'
$env:GOOGLE_UI_RETURN_CAPTURE_MS = '650'

# Fixed route/date bootstrap only. This is the unsorted search URL on purpose:
# the active probe must find and CLICK Cheapest/최저가 itself and confirm that
# the tab is selected. We no longer assume that a tfu URL means Cheapest.
$env:GOOGLE_UI_SEARCH_URL = 'https://www.google.com/travel/flights/search?tfs=CBwQAhoeEgoyMDI2LTA5LTE4agcIARIDQ0pKcgcIARIDVFBFGh4SCjIwMjYtMDktMjBqBwgBEgNUUEVyBwgBEgNDSkpAAUgBcAGCAQsI____________AZgBAQ&hl=en&gl=kr&curr=KRW'
Remove-Item Env:GOOGLE_UI_CHEAPEST_URL -ErrorAction SilentlyContinue
Remove-Item Env:BROWSER_CHANNEL -ErrorAction SilentlyContinue

Write-Host 'Google Flights explicit Cheapest-tab + transient snapshot + Booking probe'
Write-Host '  CJJ -> TPE -> CJJ'
Write-Host '  2026-09-18 ~ 2026-09-20'
Write-Host '  1 adult / Economy / KRW'
Write-Host '  actual Cheapest/최저가 click: YES'
Write-Host '  aria-selected confirmation: YES'
Write-Host '  pre-Cheapest Best-tab prices ignored: YES'
Write-Host '  disappearing cheapest snapshots preserved: YES'
Write-Host '  loading one-row premature selection: NO'
Write-Host '  return adjustment can be +₩0: YES'
Write-Host '  external seller checkout verification: NO'
Write-Host '  body-wide price fallback: NO'
Write-Host "  departure capture window: $($env:GOOGLE_UI_DEPARTURE_CAPTURE_MS) ms"
Write-Host "  return capture window: $($env:GOOGLE_UI_RETURN_CAPTURE_MS) ms"
Write-Host "  selection wait: $($env:GOOGLE_UI_SELECTION_WAIT_MS) ms"
Write-Host "  booking wait: $($env:GOOGLE_UI_BOOKING_WAIT_MS) ms"
Write-Host "  headless: $($env:BROWSER_HEADLESS)"
Write-Host ''

& $VenvPython 'scripts\google_booking_pointer_probe.py'
if ($LASTEXITCODE -ne 0) {
    throw "Google UI snapshot booking probe failed with exit code $LASTEXITCODE. Check artifacts\google-ui-win."
}

Write-Host ''
Write-Host 'Probe complete.'
Write-Host 'Paste the Cheapest/departure/return/Booking output and SUMMARY into the next ChatGPT chat.'
