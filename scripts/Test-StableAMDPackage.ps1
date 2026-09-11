[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [string]$AcceptanceRoot = '',
    [int]$AppPort = 8288,
    [int]$BackendPort = 8290,
    [switch]$PlanOnly,
    [switch]$KeepRuntime
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

if ($AppPort -lt 1 -or $AppPort -gt 65535 -or $BackendPort -lt 1 -or $BackendPort -gt 65535) {
    throw 'Acceptance ports must be within 1-65535.'
}
if ($AppPort -eq $BackendPort) {
    throw 'Application and backend acceptance ports must be different.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if ([string]::IsNullOrWhiteSpace($AcceptanceRoot)) {
    $AcceptanceRoot = Join-Path $RepoRoot "diagnostics/acceptance-package-$stamp"
}
$AcceptanceRoot = [IO.Path]::GetFullPath($AcceptanceRoot)

$buildScript = Join-Path $RepoRoot 'scripts/Build-StableAMDPackage.ps1'
if (-not (Test-Path $buildScript -PathType Leaf)) {
    throw "StableAMD package builder is missing: '$buildScript'."
}

New-Item -ItemType Directory -Path $AcceptanceRoot -Force | Out-Null
$packageOutput = Join-Path $AcceptanceRoot 'package'
$package = & $buildScript -RepoRoot $RepoRoot -OutputDirectory $packageOutput -Version '0.1.0-acceptance'
$PackageRoot = [IO.Path]::GetFullPath([string]$package.PackageRoot)

$runtimeInstaller = Join-Path $PackageRoot 'scripts/Install-StableAMDRuntime.ps1'
$launcher = Join-Path $PackageRoot 'scripts/Launch-StableAMD.ps1'
$statusScript = Join-Path $PackageRoot 'scripts/Get-StableAMDStatus.ps1'
$stopScript = Join-Path $PackageRoot 'scripts/Stop-StableAMD.ps1'
foreach ($required in @($runtimeInstaller, $launcher, $statusScript, $stopScript)) {
    if (-not (Test-Path $required -PathType Leaf)) {
        throw "Packaged acceptance component is missing: '$required'."
    }
}

# The package gets its own backend port so the acceptance copy cannot attach to the
# development repository's managed backend. Only the copied package config is changed.
$packageConfigPath = Join-Path $PackageRoot 'config/stableamd.default.json'
$config = Get-Content -Path $packageConfigPath -Raw | ConvertFrom-Json
$config.backend.port = $BackendPort
$config | ConvertTo-Json -Depth 20 | Set-Content -Path $packageConfigPath -Encoding UTF8

$runtimePlan = & $runtimeInstaller -RepoRoot $PackageRoot -PlanOnly
$planReport = [pscustomobject]@{
    schemaVersion = 1
    createdAtUtc = [DateTime]::UtcNow.ToString('o')
    mode = if ($PlanOnly) { 'plan-only' } else { 'hardware-acceptance' }
    acceptanceRoot = $AcceptanceRoot
    packageRoot = $PackageRoot
    packageZip = [string]$package.ZipPath
    appPort = $AppPort
    backendPort = $BackendPort
    runtimePlan = $runtimePlan
}

if ($PlanOnly) {
    return $planReport
}

$appProcessId = $null
$launchResult = $null
$backendStatus = $null
$health = $null
$models = $null
$success = $false
$reportPath = Join-Path $RepoRoot "diagnostics/acceptance-package-$stamp.json"
New-Item -ItemType Directory -Path (Split-Path -Parent $reportPath) -Force | Out-Null

try {
    Write-Host ''
    Write-Host 'StableAMD isolated clean-package acceptance' -ForegroundColor Cyan
    Write-Host "Acceptance root: $AcceptanceRoot"
    Write-Host 'This uses a fresh package directory and does not reuse or delete the development repository runtime.' -ForegroundColor DarkGray

    $runtimeResult = & $runtimeInstaller -RepoRoot $PackageRoot
    if ($null -eq $runtimeResult -or -not (Test-Path $runtimeResult.PythonPath -PathType Leaf)) {
        throw 'Packaged runtime bootstrap did not return a usable Python runtime.'
    }

    $launchResult = & $launcher -RepoRoot $PackageRoot -AppPort $AppPort -NoBrowser
    if ($null -eq $launchResult -or -not [bool]$launchResult.Healthy) {
        throw 'Packaged StableAMD launcher did not report a healthy application.'
    }
    if ($null -ne $launchResult.ProcessId) {
        $appProcessId = [int]$launchResult.ProcessId
    }

    $healthUrl = "http://127.0.0.1:$AppPort/api/health"
    $health = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 10
    if ([string]$health.service -ne 'StableAMD' -or [string]$health.status -ne 'ok') {
        throw "Packaged application returned an unexpected /api/health payload from '$healthUrl'."
    }

    $backendStatus = & $statusScript -RepoRoot $PackageRoot
    if ($null -eq $backendStatus -or [string]$backendStatus.Status -ne 'running' -or -not [bool]$backendStatus.Healthy) {
        throw 'Packaged managed backend is not healthy after launch.'
    }

    $models = Invoke-RestMethod -Uri "http://127.0.0.1:$AppPort/api/models" -Method Get -TimeoutSec 15

    $report = [pscustomobject]@{
        schemaVersion = 1
        createdAtUtc = [DateTime]::UtcNow.ToString('o')
        status = 'passed'
        acceptanceRoot = $AcceptanceRoot
        packageRoot = $PackageRoot
        packageZip = [string]$package.ZipPath
        appPort = $AppPort
        backendPort = $BackendPort
        runtime = $runtimeResult
        application = $launchResult
        health = $health
        backend = $backendStatus
        models = $models
    }
    $report | ConvertTo-Json -Depth 20 | Set-Content -Path $reportPath -Encoding UTF8
    $success = $true

    Write-Host ''
    Write-Host 'STABLEAMD CLEAN-PACKAGE RUNTIME ACCEPTANCE PASSED.' -ForegroundColor Green
    Write-Host "Report: $reportPath"
    return $report
}
catch {
    $failure = [pscustomobject]@{
        schemaVersion = 1
        createdAtUtc = [DateTime]::UtcNow.ToString('o')
        status = 'failed'
        acceptanceRoot = $AcceptanceRoot
        packageRoot = $PackageRoot
        appPort = $AppPort
        backendPort = $BackendPort
        error = $_.Exception.Message
        application = $launchResult
        backend = $backendStatus
        health = $health
    }
    $failure | ConvertTo-Json -Depth 20 | Set-Content -Path $reportPath -Encoding UTF8
    Write-Host "Acceptance report: $reportPath" -ForegroundColor Yellow
    throw
}
finally {
    if ($null -ne $appProcessId) {
        Stop-Process -Id $appProcessId -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $stopScript -PathType Leaf) {
        try { & $stopScript -RepoRoot $PackageRoot | Out-Null } catch { }
    }

    if ($success -and -not $KeepRuntime -and (Test-Path $AcceptanceRoot)) {
        Write-Host 'Removing successful isolated acceptance runtime. Use -KeepRuntime to retain it.' -ForegroundColor DarkGray
        Remove-Item -Path $AcceptanceRoot -Recurse -Force
    }
    elseif (-not $success) {
        Write-Host "Acceptance files were kept for diagnosis at '$AcceptanceRoot'." -ForegroundColor Yellow
    }
}
