[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$AppPort = 8188,
    [int]$AppStartupTimeoutSeconds = 30,
    [switch]$NoBrowser,
    [switch]$SkipRuntimeInstall
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

$comfyMain = Join-Path $paths.ComfyRoot 'main.py'
$comfyApiInput = Join-Path $paths.ComfyRoot 'comfy_api/input/__init__.py'
$runtimeMissing = (-not (Test-Path $paths.TheRockPython -PathType Leaf)) -or (-not (Test-Path $comfyMain -PathType Leaf)) -or (-not (Test-Path $comfyApiInput -PathType Leaf))
if ($runtimeMissing) {
    if ($SkipRuntimeInstall) {
        throw "StableAMD runtime is missing or incomplete. Expected Python '$($paths.TheRockPython)' and ComfyUI '$($paths.ComfyRoot)'."
    }

    $runtimeInstaller = Join-Path $PSScriptRoot 'Install-StableAMDRuntime.ps1'
    if (-not (Test-Path $runtimeInstaller -PathType Leaf)) {
        throw "StableAMD runtime is missing and the bootstrap installer was not found at '$runtimeInstaller'."
    }

    Write-Host ''
    Write-Host 'StableAMD runtime is missing or incomplete. Preparing the pinned Radeon runtime...' -ForegroundColor Yellow
    Write-Host 'The first launch downloads Python, the locked TheRock ROCm/PyTorch stack and ComfyUI. This can download more than 1 GB.' -ForegroundColor DarkGray
    $runtimeInstall = & $runtimeInstaller -RepoRoot $RepoRoot
    if ($null -eq $runtimeInstall -or -not (Test-Path $paths.TheRockPython -PathType Leaf) -or -not (Test-Path $comfyMain -PathType Leaf)) {
        throw 'StableAMD runtime bootstrap returned without creating the required managed runtime.'
    }
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
