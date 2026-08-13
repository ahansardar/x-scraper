param(
    [string] $BindHost = "127.0.0.1",
    [int] $Port = 8000,
    [switch] $SkipDocker,
    [switch] $NoMigrations,
    [switch] $NoHealthWait,
    [switch] $Visible,
    [switch] $Stop,
    [switch] $Restart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSCommandPath
$RunDir = Join-Path $Root "data\run_all"
$LogDir = Join-Path $RunDir "logs"
$PidFile = Join-Path $RunDir "pids.json"

function Write-Step {
    param([string] $Message)
    Write-Host ""
    Write-Host "==> $Message"
}

function Quote-Single {
    param([string] $Value)
    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-RepoCommand {
    param(
        [string] $Label,
        [string[]] $Command
    )

    Write-Step $Label
    Push-Location $Root
    try {
        & $Command[0] $Command[1..($Command.Length - 1)]
    }
    finally {
        Pop-Location
    }
}

function Test-CommandAvailable {
    param([string] $Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Wait-DockerServiceHealthy {
    param(
        [string] $Service,
        [int] $TimeoutSeconds = 90
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Push-Location $Root
        try {
            $containerId = (docker compose ps -q $Service) 2>$null
        }
        finally {
            Pop-Location
        }

        if ($containerId) {
            $status = (docker inspect --format "{{.State.Health.Status}}" $containerId) 2>$null
            if ($LASTEXITCODE -ne 0 -or -not $status) {
                $status = (docker inspect --format "{{.State.Status}}" $containerId) 2>$null
            }
            if ($status -eq "healthy" -or $status -eq "running") {
                Write-Host "$Service is $status"
                return
            }
            Write-Host "$Service is $status; waiting..."
        }
        else {
            Write-Host "$Service container is not available yet; waiting..."
        }

        Start-Sleep -Seconds 3
    }

    throw "$Service did not become healthy within $TimeoutSeconds seconds"
}

function Stop-ManagedProcesses {
    if (-not (Test-Path $PidFile)) {
        Write-Host "No run_all PID file found at $PidFile"
        return
    }

    $state = Get-Content -Raw $PidFile | ConvertFrom-Json
    foreach ($entry in @($state.processes)) {
        $pidValue = [int] $entry.pid
        $name = [string] $entry.name
        $process = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
        if ($process) {
            Write-Host "Stopping $name (pid $pidValue)"
            Stop-Process -Id $pidValue -Force
        }
        else {
            Write-Host "$name (pid $pidValue) is not running"
        }
    }

    Remove-Item -LiteralPath $PidFile -Force
}

function Get-LiveManagedProcesses {
    if (-not (Test-Path $PidFile)) {
        return @()
    }

    $state = Get-Content -Raw $PidFile | ConvertFrom-Json
    $live = @()
    foreach ($entry in @($state.processes)) {
        $process = Get-Process -Id ([int] $entry.pid) -ErrorAction SilentlyContinue
        if ($process) {
            $live += $entry
        }
    }
    return $live
}

function Start-ManagedProcess {
    param(
        [string] $Name,
        [string] $Command
    )

    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    $rootLiteral = Quote-Single $Root
    $wrappedCommand = "Set-Location -LiteralPath $rootLiteral; `$env:PYTHONPATH = 'src'; $Command"

    if ($Visible) {
        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-Command",
            $wrappedCommand
        )
        $process = Start-Process -FilePath "powershell" -ArgumentList $arguments -PassThru
    }
    else {
        $arguments = @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            $wrappedCommand
        )
        $process = Start-Process `
            -FilePath "powershell" `
            -ArgumentList $arguments `
            -RedirectStandardOutput $stdout `
            -RedirectStandardError $stderr `
            -WindowStyle Hidden `
            -PassThru
    }

    Write-Host "Started $Name (pid $($process.Id))"
    if (-not $Visible) {
        Write-Host "  stdout: $stdout"
        Write-Host "  stderr: $stderr"
    }

    return [pscustomobject]@{
        name = $Name
        pid = $process.Id
        command = $Command
        stdout = $stdout
        stderr = $stderr
    }
}

function Wait-WebReady {
    param(
        [string] $Url,
        [int] $TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "Web API responded at $Url"
                return
            }
        }
        catch {
            Write-Host "Waiting for web API at $Url"
        }
        Start-Sleep -Seconds 2
    }

    throw "Web API did not respond at $Url within $TimeoutSeconds seconds"
}

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

if ($Stop) {
    Stop-ManagedProcesses
    exit 0
}

if ($Restart) {
    Stop-ManagedProcesses
}
else {
    $liveProcesses = @(Get-LiveManagedProcesses)
    if ($liveProcesses.Count -gt 0) {
        Write-Host "run_all managed processes are already running:"
        foreach ($entry in $liveProcesses) {
            Write-Host "  $($entry.name) pid=$($entry.pid)"
        }
        Write-Host "Use .\run_all.ps1 -Stop or .\run_all.ps1 -Restart before starting another set."
        exit 0
    }
}

if (-not (Test-CommandAvailable "python")) {
    throw "python is not available on PATH"
}

if (-not $SkipDocker) {
    if (-not (Test-CommandAvailable "docker")) {
        throw "docker is not available on PATH. Install Docker Desktop or rerun with -SkipDocker if Postgres/Redis are already running."
    }

    Invoke-RepoCommand "Starting Postgres and Redis with Docker Compose" @("docker", "compose", "up", "-d")
    Wait-DockerServiceHealthy -Service "postgres"
    Wait-DockerServiceHealthy -Service "redis"
}
else {
    Write-Step "Skipping Docker Compose startup"
}

if (-not $NoMigrations) {
    Invoke-RepoCommand "Running Postgres migrations" @("python", ".\run_postgres_migrations.py")
    Invoke-RepoCommand "Running SQLite operational migrations" @("python", ".\run_migrations.py")
}
else {
    Write-Step "Skipping migrations"
}

Invoke-RepoCommand "Running startup check" @("python", ".\run_startup_check.py")

$processes = @()
$processes += Start-ManagedProcess -Name "web" -Command "python .\run_app.py --host $(Quote-Single $BindHost) --port $(Quote-Single ([string] $Port))"
$processes += Start-ManagedProcess -Name "dispatcher" -Command "python .\run_dispatcher.py"
$processes += Start-ManagedProcess -Name "worker" -Command "python .\run_worker.py"

$state = [pscustomobject]@{
    started_at = (Get-Date).ToString("o")
    root = $Root
    url = "http://$BindHost`:$Port"
    processes = $processes
}
$state | ConvertTo-Json -Depth 5 | Set-Content -Path $PidFile -Encoding UTF8

$baseUrl = "http://$BindHost`:$Port"
if (-not $NoHealthWait) {
    Wait-WebReady -Url "$baseUrl/api/health"
    Invoke-RepoCommand "Running live preflight" @("python", ".\run_preflight.py", "--base-url", $baseUrl)
}

Write-Host ""
Write-Host "X ingestion stack is running."
Write-Host "Frontend/backend URL: $baseUrl"
Write-Host "PID file: $PidFile"
Write-Host "Logs: $LogDir"
Write-Host ""
Write-Host "Useful checks:"
Write-Host "  python .\run_smoke.py --base-url $baseUrl"
Write-Host "  python .\run_health_report.py --base-url $baseUrl"
Write-Host ""
Write-Host "Stop app processes:"
Write-Host "  .\run_all.ps1 -Stop"
