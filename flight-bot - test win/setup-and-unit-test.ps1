param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

Write-Host "[1/5] Repository: $RepoRoot"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonLauncher = 'py'
    $PythonArgs = @('-3.12')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonLauncher = 'python'
    $PythonArgs = @()
} else {
    throw 'Python 3.12+ not found. Install Python first and enable the py launcher or PATH.'
}

$VenvPython = Join-Path $RepoRoot '.venv-win\Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
    Write-Host '[2/5] Creating .venv-win ...'
    & $PythonLauncher @PythonArgs -m venv '.venv-win'
} else {
    Write-Host '[2/5] Reusing existing .venv-win'
}

Write-Host '[3/5] Installing flight-bot + dev dependencies ...'
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e '.[dev]'

Write-Host '[4/5] Installing Playwright Chromium ...'
& $VenvPython -m playwright install chromium

Write-Host '[5/5] Running unit tests ...'
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "pytest failed with exit code $LASTEXITCODE" }

Write-Host ''
Write-Host 'Windows setup/unit test complete.'
Write-Host 'Next: run 02-live-cjj-tpe-visible.cmd or .\live-cjj-tpe.ps1'
