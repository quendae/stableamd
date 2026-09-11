[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$AppPort = 8188,
    [int]$AppStartupTimeoutSeconds = 30,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'StableAMD v0.1 launcher is Windows-only.'
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

if ($AppPort -lt 1 -or $AppPort -gt 65535) {
    throw "Application port '$AppPort' is outside the valid range 1-65535."
}
if ($AppStartupTimeoutSeconds -lt 5) {
    throw 'Application startup timeout must be at least 5 seconds.'
}

$runtimeModule = Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1'
if (-not (Test-Path $runtimeModule -PathType Leaf)) {
    throw "StableAMD runtime module is missing: '$runtimeModule'."
}
Import-Module $runtimeModule -Force

$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
Initialize-StableAmdRuntimeDirectories -Paths $paths

$appServer = Join-Path $RepoRoot 'app/backend/stableamd_server.py'
if (-not (Test-Path $appServer -PathType Leaf)) {
    throw "StableAMD application server is missing: '$appServer'."
}
if (-not (Test-Path $paths.TheRockPython -PathType Leaf)) {
    throw "StableAMD TheRock runtime is missing at '$($paths.TheRockPython)'. Prepare the validated gfx1030 runtime before launching the product UI."
}

$resolvedAppPort = $AppPort
$appUrl = "http://127.0.0.1:$resolvedAppPort/"
$healthUrl = "http://127.0.0.1:$resolvedAppPort/api/health"

function Get-StableAmdAppHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 3
        if ($null -ne $response -and [string]$response.service -eq 'StableAMD' -and [string]$response.status -eq 'ok') {
            return $response
        }
    }
    catch { }
    return $null
}

Write-Host ''
Write-Host 'StableAMD v0.1' -ForegroundColor Cyan
Write-Host 'Starting managed compute backend...' -ForegroundColor Cyan
$backendStatus = & (Join-Path $PSScriptRoot 'Start-StableAMD.ps1') -RepoRoot $RepoRoot
if ($null -eq $backendStatus -or -not [bool]$backendStatus.Healthy) {
    throw 'StableAMD managed compute backend did not become healthy.'
}
Write-Host "Compute backend ready: $($backendStatus.Url)" -ForegroundColor Green

$existingHealth = Get-StableAmdAppHealth
$Reused = $null -ne $existingHealth
$appProcess = $null
$stdoutPath = $null
$stderrPath = $null

if ($Reused) {
    Write-Host "StableAMD application is already reachable at $appUrl" -ForegroundColor Green
}
else {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutPath = Join-Path $paths.LogsRoot "app-$stamp.stdout.log"
    $stderrPath = Join-Path $paths.LogsRoot "app-$stamp.stderr.log"

    Write-Host "Starting StableAMD application on $appUrl ..." -ForegroundColor Cyan
    $arguments = "-s `"$appServer`" --repo-root `"$RepoRoot`" --host 127.0.0.1 --port $resolvedAppPort"
    $appProcess = Start-Process `
        -FilePath $paths.TheRockPython `
        -ArgumentList $arguments `
        -WorkingDirectory $RepoRoot `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru

    $deadline = (Get-Date).AddSeconds($AppStartupTimeoutSeconds)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        if ($appProcess.HasExited) { break }
        $health = Get-StableAmdAppHealth
        if ($null -ne $health) { break }
        Start-Sleep -Milliseconds 500
    }

    if ($null -eq $health) {
        Write-Host ''
        Write-Host '===== StableAMD application stderr tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stderrPath) {
            Get-Content -Path $stderrPath -Tail 80 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }
        Write-Host ''
        Write-Host '===== StableAMD application stdout tail =====' -ForegroundColor DarkCyan
        if (Test-Path $stdoutPath) {
            Get-Content -Path $stdoutPath -Tail 40 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
        }

        if ($null -ne $appProcess -and -not $appProcess.HasExited) {
            Stop-Process -Id $appProcess.Id -Force -ErrorAction SilentlyContinue
        }
        throw "StableAMD application did not become healthy at '$healthUrl' within $AppStartupTimeoutSeconds seconds."
    }

    Write-Host "StableAMD application ready: $appUrl" -ForegroundColor Green
}

if (-not $NoBrowser) {
    Start-Process $appUrl
}

return [pscustomobject]@{
    Status = 'running'
    Healthy = $true
    Reused = $Reused
    Url = $appUrl
    HealthUrl = $healthUrl
    ProcessId = if ($null -ne $appProcess) { $appProcess.Id } else { $null }
    StdoutLog = $stdoutPath
    StderrLog = $stderrPath
    Backend = $backendStatus
}
