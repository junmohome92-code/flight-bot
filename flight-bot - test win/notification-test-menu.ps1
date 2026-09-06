param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

function Read-DotEnv {
    param([string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $separator = $trimmed.IndexOf('=')
        if ($separator -lt 1) { continue }
        $key = $trimmed.Substring(0, $separator).Trim()
        $value = $trimmed.Substring($separator + 1).Trim()
        if ($value.Length -ge 2) {
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
                ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $values[$key] = $value
    }
    return $values
}

function Test-Health {
    param([string]$BaseUrl)
    try {
        return Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 4
    }
    catch {
        return $null
    }
}

function Wait-Health {
    param([string]$BaseUrl, [int]$Seconds = 45)
    for ($i = 0; $i -lt ($Seconds * 2); $i++) {
        $health = Test-Health -BaseUrl $BaseUrl
        if ($health) { return $health }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Invoke-AdminPost {
    param(
        [string]$BaseUrl,
        [string]$Secret,
        [string]$Path,
        [int]$TimeoutSec = 240
    )
    Write-Host ""
    Write-Host "POST $Path" -ForegroundColor Cyan
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl$Path" `
        -Headers @{ 'X-Flight-Bot-Secret' = $Secret } `
        -TimeoutSec $TimeoutSec
    $response | ConvertTo-Json -Depth 8
    return $response
}

function Read-SlotId {
    while ($true) {
        $raw = Read-Host 'Slot number (1-10)'
        $slotId = 0
        if ([int]::TryParse($raw, [ref]$slotId) -and $slotId -ge 1 -and $slotId -le 10) {
            return $slotId
        }
        Write-Host 'Enter a number from 1 to 10.' -ForegroundColor Yellow
    }
}

$EnvPath = Join-Path $RepoRoot '.env'
$EnvExamplePath = Join-Path $RepoRoot '.env.example'
if (-not (Test-Path $EnvPath)) {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    Write-Host ''
    Write-Host '.env was created from .env.example.' -ForegroundColor Yellow
    Write-Host 'Open .env and fill these three values, then run this menu again:'
    Write-Host '  TELEGRAM_BOT_TOKEN=...'
    Write-Host '  TELEGRAM_ALLOWED_CHAT_IDS=...'
    Write-Host '  ADMIN_SECRET=any-long-random-string'
    exit 2
}

$DotEnv = Read-DotEnv -Path $EnvPath
$Port = if ($DotEnv.ContainsKey('HTTP_PORT') -and $DotEnv['HTTP_PORT']) { $DotEnv['HTTP_PORT'] } else { '8080' }
$AdminSecret = if ($DotEnv.ContainsKey('ADMIN_SECRET')) { $DotEnv['ADMIN_SECRET'] } else { '' }
$TelegramToken = if ($DotEnv.ContainsKey('TELEGRAM_BOT_TOKEN')) { $DotEnv['TELEGRAM_BOT_TOKEN'] } else { '' }
$TelegramChats = if ($DotEnv.ContainsKey('TELEGRAM_ALLOWED_CHAT_IDS')) { $DotEnv['TELEGRAM_ALLOWED_CHAT_IDS'] } else { '' }
$BaseUrl = "http://127.0.0.1:$Port"

if (-not $AdminSecret) {
    Write-Host 'ADMIN_SECRET is empty in .env. Set it before notification testing.' -ForegroundColor Red
    exit 3
}
if (-not $TelegramToken -or -not $TelegramChats) {
    Write-Host 'Telegram token/chat ID is not configured in .env.' -ForegroundColor Red
    Write-Host 'Set TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_CHAT_IDS first.'
    exit 4
}

$VenvPython = Join-Path $RepoRoot '.venv-win\Scripts\python.exe'
$Artifacts = Join-Path $RepoRoot 'artifacts'
New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null
$StartedLocalProcess = $null
$StartedDocker = $false

$health = Test-Health -BaseUrl $BaseUrl
if (-not $health) {
    Write-Host ''
    Write-Host 'Flight Bot is not running.' -ForegroundColor Yellow
    Write-Host '  1. Start local Windows bot'
    Write-Host '  2. Start Docker Compose bot'
    Write-Host '  0. Exit'
    $mode = Read-Host 'Select'

    if ($mode -eq '1') {
        if (-not (Test-Path $VenvPython)) {
            Write-Host 'Windows virtual environment not found. Run 01-setup-and-unit-test.cmd first.' -ForegroundColor Red
            exit 5
        }

        $oldDb = $env:DATABASE_PATH
        $oldHeadless = $env:BROWSER_HEADLESS
        try {
            $env:DATABASE_PATH = Join-Path $Artifacts 'notification-test.db'
            $env:BROWSER_HEADLESS = 'false'
            $stdout = Join-Path $Artifacts 'notification-test-bot.stdout.log'
            $stderr = Join-Path $Artifacts 'notification-test-bot.stderr.log'
            $StartedLocalProcess = Start-Process `
                -FilePath $VenvPython `
                -ArgumentList @('-m', 'flight_bot') `
                -WorkingDirectory $RepoRoot `
                -RedirectStandardOutput $stdout `
                -RedirectStandardError $stderr `
                -PassThru
        }
        finally {
            if ($null -eq $oldDb) { Remove-Item Env:DATABASE_PATH -ErrorAction SilentlyContinue } else { $env:DATABASE_PATH = $oldDb }
            if ($null -eq $oldHeadless) { Remove-Item Env:BROWSER_HEADLESS -ErrorAction SilentlyContinue } else { $env:BROWSER_HEADLESS = $oldHeadless }
        }
        Write-Host "Local bot started. PID=$($StartedLocalProcess.Id)"
    }
    elseif ($mode -eq '2') {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Write-Host 'Docker command was not found.' -ForegroundColor Red
            exit 6
        }
        Write-Host 'Building and starting Docker Compose ...'
        & docker compose up -d --build
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up failed with exit code $LASTEXITCODE"
        }
        $StartedDocker = $true
    }
    else {
        exit 0
    }

    $health = Wait-Health -BaseUrl $BaseUrl -Seconds 60
    if (-not $health) {
        Write-Host "Bot did not become healthy at $BaseUrl" -ForegroundColor Red
        Write-Host "Check artifacts logs or run: docker compose logs --tail 200 flight-bot"
        exit 7
    }
}

Write-Host ''
Write-Host '=============================================='
Write-Host ' Flight Bot notification test menu'
Write-Host '=============================================='
Write-Host "HTTP: $BaseUrl"
Write-Host "Slots: $($health.slots_used)/$($health.slots_max)"
Write-Host "Search interval: $($health.search_interval_hours)h"
Write-Host "Daily summary hour: $($health.daily_summary_hour):00"
Write-Host "Isolated search storage: $($health.browser_search_storage_isolated)"
Write-Host ''
Write-Host 'Before testing an empty DB, send this in Telegram:' -ForegroundColor Yellow
Write-Host '/flight add CJJ TPE 2026-09-18 2026-09-20 999999'
Write-Host 'Use a high target such as 999999 to make the first target-alert test easy.'

:MenuLoop while ($true) {
    Write-Host ''
    Write-Host '1. Health / slot status'
    Write-Host '2. Test TARGET alert for one slot (real Google search)'
    Write-Host '3. Test DAILY summary for one slot (real Google search, target latch untouched)'
    Write-Host '4. Start normal target scan for ALL enabled slots'
    Write-Host '5. Start forced daily summary for ALL enabled slots (target latches untouched)'
    Write-Host '6. Show Telegram test commands'
    Write-Host '0. Exit'
    $choice = Read-Host 'Select'

    try {
        switch ($choice) {
            '1' {
                $health = Test-Health -BaseUrl $BaseUrl
                if (-not $health) {
                    Write-Host 'Bot is not reachable.' -ForegroundColor Red
                } else {
                    $health | ConvertTo-Json -Depth 6
                }
            }
            '2' {
                $slotId = Read-SlotId
                Write-Host 'This performs a REAL Google Flights search.' -ForegroundColor Yellow
                Write-Host 'If the slot is ARMED and price <= target, the one-shot target alert will be consumed.'
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path "/admin/check-slot/$slotId" -TimeoutSec 300 | Out-Null
            }
            '3' {
                $slotId = Read-SlotId
                Write-Host 'This performs a REAL Google Flights search and forces the regular summary.' -ForegroundColor Yellow
                Write-Host 'It does NOT consume/re-arm the one-shot target alert state.'
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path "/admin/daily-summary/$slotId" -TimeoutSec 300 | Out-Null
            }
            '4' {
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path '/admin/check-all' -TimeoutSec 30 | Out-Null
                Write-Host 'All-slot scan started in background. Watch Telegram and /health scan_active.'
            }
            '5' {
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path '/admin/daily-summary' -TimeoutSec 30 | Out-Null
                Write-Host 'All-slot daily-summary scan started in background. Target alert latches are untouched.'
            }
            '6' {
                Write-Host '/flight add CJJ TPE 2026-09-18 2026-09-20 999999'
                Write-Host '/flight list'
                Write-Host '/flight target 1 999998   # explicitly re-arms target alert once'
                Write-Host '/flight check 1           # manual result only, no alert'
                Write-Host '/flight delete 1'
            }
            '0' {
                break MenuLoop
            }
            default {
                Write-Host 'Unknown selection.' -ForegroundColor Yellow
            }
        }
    }
    catch {
        Write-Host "TEST ERROR: $($_.Exception.Message)" -ForegroundColor Red
    }
}

if ($StartedLocalProcess -and -not $StartedLocalProcess.HasExited) {
    $stop = Read-Host 'Stop the local bot started by this menu? (y/N)'
    if ($stop -match '^[Yy]$') {
        Stop-Process -Id $StartedLocalProcess.Id -Force
        Write-Host 'Local bot stopped.'
    } else {
        Write-Host "Local bot left running. PID=$($StartedLocalProcess.Id)"
    }
}

if ($StartedDocker) {
    Write-Host 'Docker was started by this menu and is left running.'
    Write-Host 'Stop later with: docker compose down'
}
