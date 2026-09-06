param()

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RepoRoot

$ExpectedProvider = 'google-playwright-results-observed-accepted-flow'
$ExpectedQueryContract = 'accepted-tfs-v1'
$ExpectedSlots = 10
$ExpectedSearchHours = 2
$ExpectedConcurrency = 2
$ExpectedRecoveryReloads = 2

Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue

function Invoke-Utf8JsonRequest {
    param(
        [string]$Method,
        [string]$Uri,
        [hashtable]$Headers = @{},
        [int]$TimeoutSec = 30
    )
    $handler = New-Object System.Net.Http.HttpClientHandler
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSec)
    $request = $null
    $response = $null
    try {
        $httpMethod = New-Object System.Net.Http.HttpMethod($Method)
        $request = New-Object System.Net.Http.HttpRequestMessage($httpMethod, $Uri)
        foreach ($key in $Headers.Keys) {
            $request.Headers.TryAddWithoutValidation([string]$key, [string]$Headers[$key]) | Out-Null
        }
        $response = $client.SendAsync($request).Result
        $bytes = $response.Content.ReadAsByteArrayAsync().Result
        $text = [System.Text.Encoding]::UTF8.GetString($bytes)
        if (-not $response.IsSuccessStatusCode) {
            throw ("HTTP " + [int]$response.StatusCode + " from " + $Uri + ": " + $text)
        }
        if (-not $text) { return $null }
        return ($text | ConvertFrom-Json)
    }
    finally {
        if ($response) { $response.Dispose() }
        if ($request) { $request.Dispose() }
        $client.Dispose()
        $handler.Dispose()
    }
}

function Read-DotEnv {
    param([string]$Path)
    $values = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $i = $trimmed.IndexOf('=')
        if ($i -lt 1) { continue }
        $key = $trimmed.Substring(0, $i).Trim()
        $value = $trimmed.Substring($i + 1).Trim()
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

function Get-Health {
    param([string]$BaseUrl)
    try {
        return Invoke-Utf8JsonRequest -Method 'GET' -Uri "$BaseUrl/health" -TimeoutSec 4
    }
    catch {
        return $null
    }
}

function Wait-Health {
    param([string]$BaseUrl, [int]$Seconds = 60)
    for ($i = 0; $i -lt ($Seconds * 2); $i++) {
        $health = Get-Health -BaseUrl $BaseUrl
        if ($health) { return $health }
        Start-Sleep -Milliseconds 500
    }
    return $null
}

function Test-TcpPortInUse {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        if (-not $task.Wait(800)) { return $false }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-FlightBotDockerRunning {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    try {
        $names = & docker ps --filter 'name=^/flight-bot$' --format '{{.Names}}' 2>$null
        return [bool]($names | Where-Object { $_ -eq 'flight-bot' })
    }
    catch {
        return $false
    }
}

function Assert-RuntimeContract {
    param($Health)
    $errors = @()
    if (-not $Health) { $errors += 'Health endpoint is unavailable.' }
    else {
        if ($Health.provider -ne $ExpectedProvider) {
            $errors += "Provider mismatch. Expected '$ExpectedProvider', got '$($Health.provider)'."
        }
        if ($Health.google_query_contract -ne $ExpectedQueryContract) {
            $errors += "Query contract mismatch. Expected '$ExpectedQueryContract', got '$($Health.google_query_contract)'."
        }
        if (-not [bool]$Health.provider_accepted_for_alerts) {
            $errors += 'Runtime provider is not accepted for alerts.'
        }
        if (-not [bool]$Health.browser_search_storage_isolated) {
            $errors += 'Browser search storage isolation is disabled.'
        }
        if ([bool]$Health.browser_block_assets) {
            $errors += 'Browser asset blocking must be disabled for the accepted production surface.'
        }
        if (-not [bool]$Health.cheapest_selected_full_reload) {
            $errors += 'Cheapest forced full reload contract is disabled.'
        }
        if ([int]$Health.price_unavailable_recovery_reloads -ne $ExpectedRecoveryReloads) {
            $errors += "Price recovery reload count must be $ExpectedRecoveryReloads."
        }
        if ([int]$Health.slots_max -ne $ExpectedSlots) {
            $errors += "Runtime slot limit must be $ExpectedSlots."
        }
        if ([int]$Health.slots_design_capacity -ne $ExpectedSlots) {
            $errors += "Runtime slot design capacity must be $ExpectedSlots."
        }
        if ([int]$Health.search_interval_hours -ne $ExpectedSearchHours) {
            $errors += "Search interval must be $ExpectedSearchHours hours."
        }
        if ([int]$Health.search_concurrency -ne $ExpectedConcurrency) {
            $errors += "Search concurrency must be $ExpectedConcurrency."
        }
        if ([int]$Health.active_searches -gt $ExpectedConcurrency) {
            $errors += 'Active searches exceeded the concurrency contract.'
        }
        if (-not [bool]$Health.admin_endpoint_enabled) {
            $errors += 'Admin test endpoint is disabled.'
        }
        if (-not [bool]$Health.telegram_connected) {
            $errors += 'Telegram notifier is not connected.'
        }
    }
    if ($errors.Count -gt 0) {
        Write-Host ''
        Write-Host 'RUNTIME CONTRACT CHECK FAILED' -ForegroundColor Red
        foreach ($item in $errors) { Write-Host " - $item" -ForegroundColor Red }
        Write-Host ''
        Write-Host 'A stale/older bot or bad notifier configuration may be running on this port.' -ForegroundColor Yellow
        Write-Host 'Stop the old local process or run: docker compose down'
        throw 'Runtime contract mismatch. Refusing a misleading notification test.'
    }
}

function Assert-AdminAuth {
    param([string]$BaseUrl, [string]$Secret)
    try {
        $probe = Invoke-Utf8JsonRequest `
            -Method 'POST' `
            -Uri "$BaseUrl/admin/check-slot/999999" `
            -Headers @{ 'X-Flight-Bot-Secret' = $Secret } `
            -TimeoutSec 10
        if (-not $probe.accepted) {
            throw 'Admin probe was not accepted.'
        }
        Write-Host '[preflight] Admin secret matches the running bot.' -ForegroundColor Green
    }
    catch {
        throw 'ADMIN_SECRET does not match the running bot, or the admin endpoint is unreachable. Restart the bot after changing .env.'
    }
}

function Assert-LocalEnv {
    param([hashtable]$DotEnv)
    $errors = @()
    $admin = [string]$DotEnv['ADMIN_SECRET']
    $token = [string]$DotEnv['TELEGRAM_BOT_TOKEN']
    $chats = [string]$DotEnv['TELEGRAM_ALLOWED_CHAT_IDS']
    if (-not $admin) { $errors += 'ADMIN_SECRET is empty.' }
    if (-not $token) { $errors += 'TELEGRAM_BOT_TOKEN is empty.' }
    if (-not $chats) { $errors += 'TELEGRAM_ALLOWED_CHAT_IDS is empty.' }
    if ($chats -and $chats -notmatch '^-?\d+(\s*,\s*-?\d+)*$') {
        $errors += 'TELEGRAM_ALLOWED_CHAT_IDS must contain numeric chat IDs separated by commas.'
    }
    if ($errors.Count -gt 0) {
        Write-Host ''
        Write-Host '.env PRECHECK FAILED' -ForegroundColor Red
        foreach ($item in $errors) { Write-Host " - $item" -ForegroundColor Red }
        Write-Host ''
        Write-Host 'Required example:'
        Write-Host 'TELEGRAM_BOT_TOKEN=123456:ABC...'
        Write-Host 'TELEGRAM_ALLOWED_CHAT_IDS=123456789'
        Write-Host 'ADMIN_SECRET=test123456789'
        throw 'Fix .env and run this menu again.'
    }
}

function Test-TelegramConfiguration {
    param([string]$Token, [string]$ChatIds)
    Write-Host '[preflight] Checking Telegram bot token ...'
    try {
        $me = Invoke-Utf8JsonRequest -Method 'GET' -Uri ("https://api.telegram.org/bot" + $Token + '/getMe') -TimeoutSec 10
        if (-not $me.ok) { throw 'Telegram getMe returned ok=false.' }
        Write-Host ("[preflight] Telegram bot OK: @" + $me.result.username) -ForegroundColor Green
    }
    catch {
        Write-Host '[preflight] Telegram API check failed.' -ForegroundColor Yellow
        Write-Host '           Verify the bot token and Internet connection before expecting an alert.' -ForegroundColor Yellow
        return
    }

    foreach ($chatId in ($ChatIds -split ',')) {
        $id = $chatId.Trim()
        if (-not $id) { continue }
        try {
            $chat = Invoke-Utf8JsonRequest -Method 'GET' -Uri ("https://api.telegram.org/bot" + $Token + '/getChat?chat_id=' + $id) -TimeoutSec 10
            if ($chat.ok) {
                Write-Host ("[preflight] Telegram chat reachable: " + $id) -ForegroundColor Green
            }
        }
        catch {
            Write-Host ("[preflight] Chat ID may be wrong or the bot has not been started in chat: " + $id) -ForegroundColor Yellow
        }
    }
}

function Show-RuntimeLog {
    param([bool]$DockerMode, [string]$StdoutPath, [string]$StderrPath)
    Write-Host ''
    Write-Host '=== RUNTIME SEARCH LOG (last 120 lines) ===' -ForegroundColor Cyan
    if ($DockerMode) {
        & docker compose logs --tail 120 flight-bot
        return
    }
    if (Test-Path $StdoutPath) {
        Get-Content -LiteralPath $StdoutPath -Encoding UTF8 -Tail 120
    }
    if (Test-Path $StderrPath) {
        $err = Get-Content -LiteralPath $StderrPath -Encoding UTF8 -Tail 80
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
    $response = Invoke-Utf8JsonRequest `
        -Method 'POST' `
        -Uri "$BaseUrl$Path" `
        -Headers @{ 'X-Flight-Bot-Secret' = $Secret } `
        -TimeoutSec $TimeoutSec
    Write-Host ($response | ConvertTo-Json -Depth 8)
    return $response
}

function Read-SlotId {
    while ($true) {
        $raw = Read-Host 'Slot number (1-10)'
        $slot = 0
        if ([int]::TryParse($raw, [ref]$slot) -and $slot -ge 1 -and $slot -le 10) {
            return $slot
        }
        Write-Host 'Enter a number from 1 to 10.' -ForegroundColor Yellow
    }
}

Write-Host '=================================================='
Write-Host ' Flight Bot notification test - compatibility mode'
Write-Host '=================================================='
Write-Host ("PowerShell: " + $PSVersionTable.PSVersion.ToString())
Write-Host ("Repository: " + $RepoRoot)

$EnvPath = Join-Path $RepoRoot '.env'
$EnvExamplePath = Join-Path $RepoRoot '.env.example'
if (-not (Test-Path $EnvPath)) {
    Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    Write-Host ''
    Write-Host '.env was created from .env.example.' -ForegroundColor Yellow
    Write-Host 'Fill these values and run 03-notification-test-menu.cmd again:'
    Write-Host 'TELEGRAM_BOT_TOKEN=...'
    Write-Host 'TELEGRAM_ALLOWED_CHAT_IDS=...'
    Write-Host 'ADMIN_SECRET=test123456789'
    exit 2
}

$DotEnv = Read-DotEnv -Path $EnvPath
Assert-LocalEnv -DotEnv $DotEnv

$PortText = [string]$DotEnv['HTTP_PORT']
if (-not $PortText) { $PortText = '8080' }
$Port = 0
if (-not [int]::TryParse($PortText, [ref]$Port) -or $Port -lt 1 -or $Port -gt 65535) {
    throw 'HTTP_PORT must be an integer from 1 to 65535.'
}
$BaseUrl = "http://127.0.0.1:$Port"
$AdminSecret = [string]$DotEnv['ADMIN_SECRET']
$TelegramToken = [string]$DotEnv['TELEGRAM_BOT_TOKEN']
$TelegramChats = [string]$DotEnv['TELEGRAM_ALLOWED_CHAT_IDS']

Test-TelegramConfiguration -Token $TelegramToken -ChatIds $TelegramChats

$Artifacts = Join-Path $RepoRoot 'artifacts'
$RuntimeDebug = Join-Path $Artifacts 'runtime-alert-test'
New-Item -ItemType Directory -Force -Path $RuntimeDebug | Out-Null
$StdoutPath = Join-Path $RuntimeDebug 'bot.stdout.log'
$StderrPath = Join-Path $RuntimeDebug 'bot.stderr.log'
$VenvPython = Join-Path $RepoRoot '.venv-win\Scripts\python.exe'
$StartedLocal = $null
$DockerMode = $false

$health = Get-Health -BaseUrl $BaseUrl
if ($health) {
    Write-Host ''
    Write-Host '[preflight] Existing Flight Bot runtime detected.' -ForegroundColor Yellow
    Assert-RuntimeContract -Health $health
    Assert-AdminAuth -BaseUrl $BaseUrl -Secret $AdminSecret
    $DockerMode = Test-FlightBotDockerRunning
    if ($DockerMode) {
        Write-Host '[preflight] Existing runtime source: Docker container flight-bot' -ForegroundColor Green
    }
    else {
        Write-Host '[preflight] Existing runtime source: local/external process' -ForegroundColor Green
    }
    Write-Host '[preflight] Existing runtime matches the required contract.' -ForegroundColor Green
}
else {
    if (Test-TcpPortInUse -HostName '127.0.0.1' -Port $Port) {
        throw "Port $Port is already in use, but it is not a compatible Flight Bot health endpoint. Stop that process first."
    }

    Write-Host ''
    Write-Host 'Flight Bot is not running.' -ForegroundColor Yellow
    Write-Host '1. Start LOCAL Windows runtime (visible browser)'
    Write-Host '2. Start DOCKER runtime (headless browser)'
    Write-Host '0. Exit'
    $runMode = Read-Host 'Select'

    if ($runMode -eq '1') {
        if (-not (Test-Path $VenvPython)) {
            throw 'Windows virtual environment not found. Run 01-setup-and-unit-test.cmd first.'
        }
        Remove-Item -LiteralPath $StdoutPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $StderrPath -Force -ErrorAction SilentlyContinue

        $oldDb = $env:DATABASE_PATH
        $oldHeadless = $env:BROWSER_HEADLESS
        $oldBlockAssets = $env:BROWSER_BLOCK_ASSETS
        $oldDebug = $env:BROWSER_DEBUG_DIR
        $oldConcurrency = $env:SEARCH_CONCURRENCY
        $oldStagger = $env:SEARCH_STAGGER_SECONDS
        $oldUnbuffered = $env:PYTHONUNBUFFERED
        $oldUtf8 = $env:PYTHONUTF8
        $oldIoEncoding = $env:PYTHONIOENCODING
        try {
            $env:DATABASE_PATH = Join-Path $Artifacts 'notification-test.db'
            $env:BROWSER_HEADLESS = 'false'
            $env:BROWSER_BLOCK_ASSETS = 'false'
            $env:BROWSER_DEBUG_DIR = $RuntimeDebug
            $env:SEARCH_CONCURRENCY = '2'
            $env:SEARCH_STAGGER_SECONDS = '5'
            $env:PYTHONUNBUFFERED = '1'
            $env:PYTHONUTF8 = '1'
            $env:PYTHONIOENCODING = 'utf-8'
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
            if ($null -eq $oldBlockAssets) { Remove-Item Env:BROWSER_BLOCK_ASSETS -ErrorAction SilentlyContinue } else { $env:BROWSER_BLOCK_ASSETS = $oldBlockAssets }
            if ($null -eq $oldDebug) { Remove-Item Env:BROWSER_DEBUG_DIR -ErrorAction SilentlyContinue } else { $env:BROWSER_DEBUG_DIR = $oldDebug }
            if ($null -eq $oldConcurrency) { Remove-Item Env:SEARCH_CONCURRENCY -ErrorAction SilentlyContinue } else { $env:SEARCH_CONCURRENCY = $oldConcurrency }
            if ($null -eq $oldStagger) { Remove-Item Env:SEARCH_STAGGER_SECONDS -ErrorAction SilentlyContinue } else { $env:SEARCH_STAGGER_SECONDS = $oldStagger }
            if ($null -eq $oldUnbuffered) { Remove-Item Env:PYTHONUNBUFFERED -ErrorAction SilentlyContinue } else { $env:PYTHONUNBUFFERED = $oldUnbuffered }
            if ($null -eq $oldUtf8) { Remove-Item Env:PYTHONUTF8 -ErrorAction SilentlyContinue } else { $env:PYTHONUTF8 = $oldUtf8 }
            if ($null -eq $oldIoEncoding) { Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue } else { $env:PYTHONIOENCODING = $oldIoEncoding }
        }
    }
    elseif ($runMode -eq '2') {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw 'Docker command not found.'
        }
        & docker info *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not running.' }
        & docker compose config *> $null
        if ($LASTEXITCODE -ne 0) { throw 'docker compose config validation failed.' }
        $DockerMode = $true
        & docker compose up -d --build
        if ($LASTEXITCODE -ne 0) { throw 'docker compose up failed.' }
    }
    else {
        exit 0
    }

    $health = Wait-Health -BaseUrl $BaseUrl -Seconds 90
    if (-not $health) {
        Show-RuntimeLog -DockerMode $DockerMode -StdoutPath $StdoutPath -StderrPath $StderrPath
        throw "Bot health check failed at $BaseUrl"
    }
    Assert-RuntimeContract -Health $health
    Assert-AdminAuth -BaseUrl $BaseUrl -Secret $AdminSecret

    if ($runMode -eq '1' -and [bool]$health.browser_headless) {
        throw 'Local visible test unexpectedly started in headless mode.'
    }
    if ($runMode -eq '2' -and -not [bool]$health.browser_headless) {
        throw 'Docker test unexpectedly started in headed mode.'
    }
}

Write-Host ''
Write-Host '=================================================='
Write-Host ' Runtime ready'
Write-Host '=================================================='
Write-Host "HTTP: $BaseUrl"
Write-Host "Provider: $($health.provider)"
Write-Host "Query contract: $($health.google_query_contract)"
Write-Host "Slots: $($health.slots_used)/$($health.slots_max)"
Write-Host "Search interval: $($health.search_interval_hours) hours"
Write-Host "Search concurrency: $($health.search_concurrency)"
Write-Host "Search stagger: $($health.search_stagger_seconds) seconds"
Write-Host "Daily summary hour: $($health.daily_summary_hour):00"
Write-Host "Browser headless: $($health.browser_headless)"
Write-Host "Storage isolated: $($health.browser_search_storage_isolated)"
Write-Host "Cheapest forced reload: $($health.cheapest_selected_full_reload)"
Write-Host "Price recovery reloads: $($health.price_unavailable_recovery_reloads)"
Write-Host "Telegram connected: $($health.telegram_connected)"
Write-Host ''
Write-Host 'If the isolated test DB has no slot, send this in Telegram:' -ForegroundColor Yellow
Write-Host '/flight add CJJ TPE 2026-09-18 2026-09-20 999999'
Write-Host 'Then use menu option 2 with slot 1.'

:MenuLoop while ($true) {
    Write-Host ''
    Write-Host '1. Show health / runtime contract'
    Write-Host '2. Test TARGET alert for one slot (real Google search)'
    Write-Host '3. Test DAILY summary for one slot (real Google search)'
    Write-Host '4. Show runtime search logs'
    Write-Host '0. Exit'
    $choice = Read-Host 'Select'

    try {
        switch ($choice) {
            '1' {
                $health = Get-Health -BaseUrl $BaseUrl
                Assert-RuntimeContract -Health $health
                Write-Host ($health | ConvertTo-Json -Depth 8)
            }
            '2' {
                $slot = Read-SlotId
                if ($health.browser_headless) {
                    Write-Host 'Docker/headless mode: browser actions are not visible. Use logs for stage verification.' -ForegroundColor Yellow
                }
                else {
                    Write-Host 'Expected visible flow: Cheapest click -> forced full reload -> direct result capture.' -ForegroundColor Yellow
                }
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path "/admin/check-slot/$slot" -TimeoutSec 320 | Out-Null
                Start-Sleep -Milliseconds 500
                Show-RuntimeLog -DockerMode $DockerMode -StdoutPath $StdoutPath -StderrPath $StderrPath
            }
            '3' {
                $slot = Read-SlotId
                Write-Host 'This forces one daily summary and does not consume/re-arm the one-shot target latch.' -ForegroundColor Yellow
                Invoke-AdminPost -BaseUrl $BaseUrl -Secret $AdminSecret -Path "/admin/daily-summary/$slot" -TimeoutSec 320 | Out-Null
                Start-Sleep -Milliseconds 500
                Show-RuntimeLog -DockerMode $DockerMode -StdoutPath $StdoutPath -StderrPath $StderrPath
            }
            '4' {
                Show-RuntimeLog -DockerMode $DockerMode -StdoutPath $StdoutPath -StderrPath $StderrPath
            }
            '0' { break MenuLoop }
            default { Write-Host 'Unknown selection.' -ForegroundColor Yellow }
        }
    }
    catch {
        Write-Host ("TEST ERROR: " + $_.Exception.Message) -ForegroundColor Red
        Show-RuntimeLog -DockerMode $DockerMode -StdoutPath $StdoutPath -StderrPath $StderrPath
    }
}

if ($StartedLocal -and -not $StartedLocal.HasExited) {
    $stop = Read-Host 'Stop the local bot started by this menu? (y/N)'
    if ($stop -match '^[Yy]$') {
        Stop-Process -Id $StartedLocal.Id -Force
        Write-Host 'Local bot stopped.'
    }
    else {
        Write-Host ("Local bot left running. PID=" + $StartedLocal.Id)
    }
}
if ($DockerMode) {
    Write-Host 'Docker runtime may still be running. Stop it with: docker compose down'
}
