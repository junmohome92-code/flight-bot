param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

function Assert-LastExitCode {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Write-Host "[1/6] Repository: $RepoRoot"

$PythonLauncher = $null
$PythonArgs = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.12 -c "import sys; print(sys.version)" *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[2/6] Python 3.12 runtime not found. Installing with Windows Python launcher ...'
        & py install 3.12
        Assert-LastExitCode 'Python 3.12 installation'
        & py -3.12 -c "import sys; print(sys.version)" *> $null
        Assert-LastExitCode 'Python 3.12 verification'
    } else {
        Write-Host '[2/6] Python 3.12 runtime found.'
    }
    $PythonLauncher = 'py'
    $PythonArgs = @('-3.12')
}
elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw 'Python exists but is older than 3.12. Install Python 3.12, then run this file again.'
    }
    Write-Host '[2/6] Python 3.12+ runtime found.'
    $PythonLauncher = 'python'
}
else {
    throw 'Python is not installed. Install Python 3.12 from python.org, then run this file again.'
}

$VenvPath = Join-Path $RepoRoot '.venv-provider-poc'
$VenvPython = Join-Path $VenvPath 'Scripts\python.exe'

if (-not (Test-Path $VenvPython)) {
    if (Test-Path $VenvPath) {
        Write-Host '[3/6] Removing incomplete .venv-provider-poc ...'
        Remove-Item -Recurse -Force $VenvPath
    }
    Write-Host '[3/6] Creating isolated .venv-provider-poc ...'
    & $PythonLauncher @PythonArgs -m venv $VenvPath
    Assert-LastExitCode 'Virtual environment creation'
    if (-not (Test-Path $VenvPython)) {
        throw "Virtual environment creation did not produce $VenvPython"
    }
} else {
    Write-Host '[3/6] Reusing isolated .venv-provider-poc'
}

Write-Host '[4/6] Installing only Naver provider POC dependencies ...'
& $VenvPython -m pip install --upgrade pip
Assert-LastExitCode 'pip upgrade'
& $VenvPython -m pip install -r 'provider-poc-requirements.txt'
Assert-LastExitCode 'Naver POC dependency installation'

Write-Host '[5/6] Checking Microsoft Edge ...'
$EdgeCandidates = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { $_ -and (Test-Path $_) }
if (-not $EdgeCandidates) {
    throw 'Microsoft Edge was not found. Install/update Edge, then run this file again.'
}
Write-Host ("[5/6] Edge found: " + $EdgeCandidates[0])

Write-Host '[6/6] Running Naver/Telegram E2E contract tests ...'
& $VenvPython -m pytest -q tests/test_provider_poc.py tests/test_windows_test_harness.py
Assert-LastExitCode 'Naver/Telegram E2E contract tests'

Write-Host ''
Write-Host 'Windows Naver test setup complete.'
Write-Host 'Next:'
Write-Host '  02-NAVER-flight-test.bat'
Write-Host '  03-NAVER-TELEGRAM-E2E.bat'
