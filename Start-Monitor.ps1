param(
    [switch]$NoVenv
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runtimeDir = Join-Path $projectRoot ".runtime"
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Get-PythonCommand {
    param([switch]$SkipVenv)

    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    if ((-not $SkipVenv) -and (Test-Path $venvPython)) {
        return @{ FilePath = $venvPython; BaseArgs = @() }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source) {
        return @{ FilePath = $python.Source; BaseArgs = @() }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and $py.Source) {
        return @{ FilePath = $py.Source; BaseArgs = @("-3") }
    }

    throw "Python not found. Install Python or create .venv first."
}

function Get-RunningProcessFromPidFile {
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

    $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $pidText" -ErrorAction SilentlyContinue
    if ($existing -and $existing.CommandLine -like "*$ScriptName*") {
        return $existing
    }

    return $null
}

function Get-RunningProcessByScript {
    param(
        [string]$ScriptName
    )

    $projectHint = $projectRoot.Replace("\\", "\\\\")
    $all = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='python3.11.exe' OR Name='py.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $all) {
        if ($p.CommandLine -and $p.CommandLine -like "*$ScriptName*" -and $p.CommandLine -like "*$projectHint*") {
            return $p
        }
    }
    return $null
}

function Start-TrackedProcess {
    param(
        [string]$Name,
        [string]$ScriptName,
        [string]$PidFile,
        [string]$LogFile,
        [string]$PythonPath,
        [string[]]$PythonBaseArgs
    )

    $alreadyRunning = Get-RunningProcessFromPidFile -PidFile $PidFile -ScriptName $ScriptName
    if ($alreadyRunning) {
        Write-Host "$Name already running (PID $($alreadyRunning.ProcessId))."
        return
    }

    $alreadyRunningByScan = Get-RunningProcessByScript -ScriptName $ScriptName
    if ($alreadyRunningByScan) {
        Set-Content -Path $PidFile -Value $alreadyRunningByScan.ProcessId -Encoding ascii
        Write-Host "$Name already running (PID $($alreadyRunningByScan.ProcessId))."
        return
    }

    $allArgs = @()
    $allArgs += $PythonBaseArgs
    $allArgs += @($ScriptName)

    $proc = Start-Process -FilePath $PythonPath -ArgumentList $allArgs -WorkingDirectory $projectRoot -PassThru -WindowStyle Normal
    Set-Content -Path $PidFile -Value $proc.Id -Encoding ascii

    "[$(Get-Date -Format s)] Started $Name PID=$($proc.Id)" | Add-Content -Path $LogFile -Encoding utf8
    Write-Host "Started $Name (PID $($proc.Id))."
}

$py = Get-PythonCommand -SkipVenv:$NoVenv
$pythonPath = [string]$py.FilePath
$pythonBaseArgs = [string[]]$py.BaseArgs

$dashboardPidFile = Join-Path $runtimeDir "dashboard.pid"
$agentPidFile = Join-Path $runtimeDir "agent.pid"
$startLogFile = Join-Path $runtimeDir "start-monitor.log"

Start-TrackedProcess -Name "Dashboard" -ScriptName "dashboard.py" -PidFile $dashboardPidFile -LogFile $startLogFile -PythonPath $pythonPath -PythonBaseArgs $pythonBaseArgs
Start-TrackedProcess -Name "Agent" -ScriptName "agent.py" -PidFile $agentPidFile -LogFile $startLogFile -PythonPath $pythonPath -PythonBaseArgs $pythonBaseArgs

Write-Host "Dashboard URL: http://127.0.0.1:5000"
Write-Host "PID files: $dashboardPidFile and $agentPidFile"
