$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectRoot ".runtime"

function Get-TrackedProcess {
    param(
        [string]$PidFile,
        [string]$ScriptName
    )

    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $pidText = (Get-Content $PidFile -Raw).Trim()
    if (-not $pidText) {
        return $null
    }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $pidText" -ErrorAction SilentlyContinue
    if ($proc -and $proc.CommandLine -and $proc.CommandLine -like "*$ScriptName*") {
        return $proc
    }

    return $null
}

function Get-RunningByScript {
    param([string]$ScriptName)

    $all = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.11.exe' OR Name='py.exe'" -ErrorAction SilentlyContinue

    $matches = @()
    foreach ($p in $all) {
        if ($p.CommandLine -and $p.CommandLine -like "*$ScriptName*") {
            $matches += $p
        }
    }

    return $matches
}

function Stop-MonitorProcess {
    param(
        [string]$Name,
        [string]$ScriptName,
        [string]$PidFile
    )

    $procs = @()

    $tracked = Get-TrackedProcess -PidFile $PidFile -ScriptName $ScriptName
    if ($tracked) {
        $procs += $tracked
    }

    $scanned = @(Get-RunningByScript -ScriptName $ScriptName)
    foreach ($p in $scanned) {
        if (-not ($procs | Where-Object { $_.ProcessId -eq $p.ProcessId })) {
            $procs += $p
        }
    }

    if ($procs.Count -eq 0) {
        Write-Host "$Name is not running."
        if (Test-Path $PidFile) {
            Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
        }
        return
    }

    foreach ($proc in $procs) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Name (PID $($proc.ProcessId))."
    }

    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

$dashboardPidFile = Join-Path $runtimeDir "dashboard.pid"
$agentPidFile = Join-Path $runtimeDir "agent.pid"

Stop-MonitorProcess -Name "Agent" -ScriptName "agent.py" -PidFile $agentPidFile
Stop-MonitorProcess -Name "Dashboard" -ScriptName "dashboard.py" -PidFile $dashboardPidFile

Write-Host "Monitor stop sequence complete."
