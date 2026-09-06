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
        $i = $trimmed.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $trimmed.Substring(0, $i).Trim()
        $value = $trimmed.Substring($i + 1).Trim().Trim('"').Trim("'")
        $values[$key] = $value
    }
    return $values
}

function Get-Health {
    param([string]$BaseUrl)
    try { return Invoke-RestMethod -Method Get -Uri "$BaseUrl/health" -TimeoutSec 4 }
    catch { return $null }
}

function Wait-Health {
    param([string]$BaseUrl, [int]$Seconds = 60)
    for ($i = 0; $i -lt ($Seconds * 2); $i++) {
        $health = Get-Health $BaseUrl
        if ($health) { return $health }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Read-SlotId {
    while ($true) {
        $raw = Read-Host 'Slot number (1-10)'
        $slot = 0
        if ([int]::TryParse($raw, [ref]$slot) -and $slot -ge 1 -and $slot -le 10) {
            return $slot
        }
        Write-Host '1~10 사이 숫자를 입력하세요.' -ForegroundColor Yellow
    }
}

function Show-RuntimeLog {
    param([bool]$DockerMode, [string]$StdoutPath, [string]$StderrPath)
    Write-Host ''
    Write-Host '=== RUNTIME SEARCH LOG (last 80 lines) ===' -ForegroundColor Cyan
    if ($DockerMode) {
        & docker compose logs --tail 80 flight-bot
        return
    }
    if (Test-Path $StdoutPath) {
        Get-Content -LiteralPath $StdoutPath -Tail 80
    }
    if (Test-Path $StderrPath) {
        $err = Get-Content -LiteralPath $StderrPath -Tail 40
        if ($err) {
            Write-Host '--- stderr ---' -ForegroundColor Yellow
            $err
        }
    }
}

function Invoke-AdminPost {
    param([string]$BaseUrl, [string]$Secret, [string]$Path, [int]$TimeoutSec = 320)
    Write-Host ''
    Write-Host "POST $Path" -ForegroundColor Cyan
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl$Path" `
        -Headers @{ 'X-Flight-Bot-Secret' = $Secret } `
        -TimeoutSec $TimeoutSec
    Write-Host ($response | ConvertTo-Json -Depth 8)
    return $response
}

$EnvPath = Join-Path $RepoRoot '.env'
if (-not (Test-Path $EnvPath)) {
    Copy-Item -LiteralPath (Join-Path $RepoRoot '.env.example') -Destination $EnvPath
    Write-Host '.env 파일을 만들었습니다.' -ForegroundColor Yellow
    Write-Host '아래 값을 넣고 다시 실행하세요:'
    Write-Host 'TELEGRAM_BOT_TOKEN=...'
    Write-Host 'TELEGRAM_ALLOWED_CHAT_IDS=...'
    Write-Host 'ADMIN_SECRET=test123456789'
    exit 2
}

$DotEnv = Read-DotEnv $EnvPath
$Port = if ($DotEnv['HTTP_PORT']) { $DotEnv['HTTP_PORT'] } else { '8080' }
$AdminSecret = $DotEnv['ADMIN_SECRET']
$TelegramToken = $DotEnv['TELEGRAM_BOT_TOKEN']
$TelegramChats = $DotEnv['TELEGRAM_ALLOWED_CHAT_IDS']
$BaseUrl = "http://127.0.0.1:$Port"

if (-not $AdminSecret) {
    Write-Host 'ADMIN_SECRET가 비어 있습니다. .env에 예: ADMIN_SECRET=test123456789 를 넣으세요.' -ForegroundColor Red
    exit 3
}
if (-not $TelegramToken -or -not $TelegramChats) {
    Write-Host 'TELEGRAM_BOT_TOKEN 또는 TELEGRAM_ALLOWED_CHAT_IDS가 비어 있습니다.' -ForegroundColor Red
    exit 4
}

$Artifacts = Join-Path $RepoRoot 'artifacts'
$RuntimeDebug = Join-Path $Artifacts 'runtime-alert-test'
New-Item -ItemType Directory -Force -Path $RuntimeDebug | Out-Null
$StdoutPath = Join-Path $RuntimeDebug 'bot.stdout.log'
$StderrPath = Join-Path $RuntimeDebug 'bot.stderr.log'
$VenvPython = Join-Path $RepoRoot '.venv-win\Scripts\python.exe'
$StartedLocal = $null
$DockerMode = $false

$health = Get-Health $BaseUrl
if (-not $health) {
    Write-Host ''
    Write-Host 'Flight Bot이 실행 중이 아닙니다.' -ForegroundColor Yellow
    Write-Host '1. Windows 로컬로 실행 (브라우저 보임)'
    Write-Host '2. Docker Compose로 실행 (headless)'
    Write-Host '0. 종료'
    $runMode = Read-Host '선택'

    if ($runMode -eq '1') {
        if (-not (Test-Path $VenvPython)) {
            Write-Host '먼저 01-setup-and-unit-test.cmd를 실행하세요.' -ForegroundColor Red
            exit 5
        }
        $oldDb = $env:DATABASE_PATH
        $oldHeadless = $env:BROWSER_HEADLESS
        $oldDebug = $env:BROWSER_DEBUG_DIR
        $oldUnbuffered = $env:PYTHONUNBUFFERED
        try {
            $env:DATABASE_PATH = Join-Path $Artifacts 'notification-test.db'
            $env:BROWSER_HEADLESS = 'false'
            $env:BROWSER_DEBUG_DIR = $RuntimeDebug
            $env:PYTHONUNBUFFERED = '1'
            $StartedLocal = Start-Process `
                -FilePath $VenvPython `
                -ArgumentList @('-m', 'flight_bot') `
                -WorkingDirectory $RepoRoot `
                -RedirectStandardOutput $StdoutPath `
                -RedirectStandardError $StderrPath `
                -PassThru
        }
        finally {
            if ($null -eq $oldDb) { Remove-Item Env:DATABASE_PATH -ErrorAction SilentlyContinue } else { $env:DATABASE_PATH = $oldDb }
            if ($null -eq $oldHeadless) { Remove-Item Env:BROWSER_HEADLESS -ErrorAction SilentlyContinue } else { $env:BROWSER_HEADLESS = $oldHeadless }
            if ($null -eq $oldDebug) { Remove-Item Env:BROWSER_DEBUG_DIR -ErrorAction SilentlyContinue } else { $env:BROWSER_DEBUG_DIR = $oldDebug }
            if ($null -eq $oldUnbuffered) { Remove-Item Env:PYTHONUNBUFFERED -ErrorAction SilentlyContinue } else { $env:PYTHONUNBUFFERED = $oldUnbuffered }
        }
    }
    elseif ($runMode -eq '2') {
        $DockerMode = $true
        & docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed' }
    }
    else { exit 0 }

    $health = Wait-Health $BaseUrl 60
    if (-not $health) {
        Show-RuntimeLog $DockerMode $StdoutPath $StderrPath
        throw "Bot health check failed: $BaseUrl"
    }
}

Write-Host ''
Write-Host '=================================================='
Write-Host ' Flight Bot REAL notification test'
Write-Host '=================================================='
Write-Host "Provider: $($health.provider)"
Write-Host "Slots: $($health.slots_used)/$($health.slots_max)"
Write-Host "Cheapest forced reload: $($health.cheapest_selected_full_reload)"
Write-Host "Price recovery reloads: $($health.price_unavailable_recovery_reloads)"
Write-Host ''
Write-Host '슬롯이 없으면 Telegram에 먼저 입력:' -ForegroundColor Yellow
Write-Host '/flight add CJJ TPE 2026-09-18 2026-09-20 999999'

:MenuLoop while ($true) {
    Write-Host ''
    Write-Host '1. Health 확인'
    Write-Host '2. 목표가 알림 테스트 (슬롯 1개 / 실제 Google 검색)'
    Write-Host '3. 정기알림 테스트 (슬롯 1개 / 실제 Google 검색)'
    Write-Host '4. 검색 로그 보기'
    Write-Host '0. 종료'
    $choice = Read-Host '선택'

    try {
        switch ($choice) {
            '1' {
                $health = Get-Health $BaseUrl
                Write-Host ($health | ConvertTo-Json -Depth 8)
            }
            '2' {
                $slot = Read-SlotId
                Write-Host '브라우저에서 반드시 Cheapest 선택 -> full reload가 보여야 정상입니다.' -ForegroundColor Yellow
                Invoke-AdminPost $BaseUrl $AdminSecret "/admin/check-slot/$slot" 320 | Out-Null
                Start-Sleep -Milliseconds 300
                Show-RuntimeLog $DockerMode $StdoutPath $StderrPath
            }
            '3' {
                $slot = Read-SlotId
                Write-Host '실제 Google 검색 후 정기알림을 강제로 1회 보냅니다.' -ForegroundColor Yellow
                Invoke-AdminPost $BaseUrl $AdminSecret "/admin/daily-summary/$slot" 320 | Out-Null
                Start-Sleep -Milliseconds 300
                Show-RuntimeLog $DockerMode $StdoutPath $StderrPath
            }
            '4' { Show-RuntimeLog $DockerMode $StdoutPath $StderrPath }
            '0' { break MenuLoop }
            default { Write-Host '잘못된 선택입니다.' -ForegroundColor Yellow }
        }
    }
    catch {
        Write-Host "TEST ERROR: $($_.Exception.Message)" -ForegroundColor Red
        Show-RuntimeLog $DockerMode $StdoutPath $StderrPath
    }
}

if ($StartedLocal -and -not $StartedLocal.HasExited) {
    $stop = Read-Host '이 메뉴가 실행한 로컬 봇을 종료할까요? (y/N)'
    if ($stop -match '^[Yy]$') { Stop-Process -Id $StartedLocal.Id -Force }
}
if ($DockerMode) {
    Write-Host 'Docker는 계속 실행합니다. 종료 명령: docker compose down'
}
