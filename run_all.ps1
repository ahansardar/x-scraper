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

function Test-DockerDaemonResponding {
    try {
        docker version --format "{{.Server.Version}}" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Find-DockerDesktopExecutable {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return $null
}

function Ensure-DockerDesktopRunning {
    param([int] $TimeoutSeconds = 120)

    if (Test-DockerDaemonResponding) {
        Write-Host "Docker daemon is already responding."
        return
    }

    $dockerDesktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $dockerDesktopProcess) {
        $exe = Find-DockerDesktopExecutable
        if (-not $exe) {
            throw "Docker daemon is not responding and Docker Desktop.exe could not be found. Install Docker Desktop or start it manually, then rerun."
        }
        Write-Host "Docker Desktop is not running; starting $exe"
        Start-Process -FilePath $exe | Out-Null
    }
    else {
        Write-Host "Docker Desktop process is running; waiting for its backend to become ready..."
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerDaemonResponding) {
            Write-Host "Docker daemon is ready."
            return
        }
        Start-Sleep -Seconds 5
    }

    throw "Docker daemon did not become ready within $TimeoutSeconds seconds. Check Docker Desktop for errors (e.g. WSL2/VM startup failures) and rerun."
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

function Get-ManagedProcessScriptNames {
    return @("run_app.py", "run_dispatcher.py", "run_worker.py")
}

function Stop-StrayManagedProcesses {
    # Historically Start-ManagedProcess launched a nested "powershell -Command"
    # wrapper (itself invoking python with a Set-Location + relative ".\script.py"
    # path) and recorded *that wrapper's* PID in pids.json; the actual python.exe
    # was a child of the wrapper. Stop-Process on the wrapper PID alone does not
    # kill its children on Windows, so every -Stop left an orphaned, still
    # running, still-Postgres/Redis-connected python.exe behind. This sweep
    # catches those orphans (and any future ones) by matching command lines
    # directly instead of trusting only the PID file.
    #
    # Deliberately NOT scoped to $Root: those orphaned processes were launched
    # via "Set-Location $Root; python .\script.py", so their CommandLine only
    # ever shows the relative script name, never the repo's absolute path --
    # a $Root substring filter would silently miss exactly the processes this
    # function exists to catch. This matches only on the three script names
    # run_all.ps1 itself manages, which is an acceptable scope on a
    # single-project dev machine.
    $fragments = Get-ManagedProcessScriptNames
    $strays = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) {
            return $false
        }
        foreach ($fragment in $fragments) {
            if ($cmd -match [regex]::Escape($fragment)) {
                return $true
            }
        }
        return $false
    }
    foreach ($proc in @($strays)) {
        Write-Host "Stopping stray managed process (pid $($proc.ProcessId)): $($proc.CommandLine)"
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Stop-ManagedProcesses {
    if (Test-Path $PidFile) {
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
    else {
        Write-Host "No run_all PID file found at $PidFile"
    }

    Stop-StrayManagedProcesses
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
        [string[]] $Arguments
    )

    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    # Launch python.exe directly (not via a nested "powershell -Command"
    # wrapper) so the PID recorded below IS the process that must be
    # stopped later -- see Stop-StrayManagedProcesses for why the old
    # wrapper-PID approach leaked orphaned python.exe processes.
    $env:PYTHONPATH = "src"

    if ($Visible) {
        $process = Start-Process -FilePath "python" -ArgumentList $Arguments -WorkingDirectory $Root -PassThru
    }
    else {
        $process = Start-Process `
            -FilePath "python" `
            -ArgumentList $Arguments `
            -WorkingDirectory $Root `
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
        command = ($Arguments -join " ")
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
    # Nothing tracked is alive, but a pre-fix run (or a crashed run_all.ps1)
    # may have left orphaned python.exe processes untracked by any PID file.
    # Sweep them before starting a fresh, correctly-tracked set.
    Stop-StrayManagedProcesses
}

if (-not (Test-CommandAvailable "python")) {
    throw "python is not available on PATH"
}

if (-not $SkipDocker) {
    if (-not (Test-CommandAvailable "docker")) {
        throw "docker is not available on PATH. Install Docker Desktop or rerun with -SkipDocker if Postgres/Redis are already running."
    }

    Write-Step "Ensuring Docker Desktop is running"
    Ensure-DockerDesktopRunning

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
$processes += Start-ManagedProcess -Name "web" -Arguments @(".\run_app.py", "--host", $BindHost, "--port", [string] $Port)
$processes += Start-ManagedProcess -Name "dispatcher" -Arguments @(".\run_dispatcher.py")
$processes += Start-ManagedProcess -Name "worker" -Arguments @(".\run_worker.py")

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
