[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [switch]$RepairState
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$state = Read-StableAmdBackendState -Path $paths.BackendStatePath

if ($null -eq $state) {
    return [pscustomobject]@{
        Status = 'stopped'
        Running = $false
        Healthy = $false
        StaleState = $false
        Pid = $null
        Url = $null
        Device = $null
        StatePath = $paths.BackendStatePath
    }
}

$statePid = $null
try { $statePid = [int]$state.pid } catch { $statePid = $null }
if ($null -eq $statePid -or $statePid -le 0) {
    if ($RepairState) { Remove-StableAmdBackendState -Path $paths.BackendStatePath }
    return [pscustomobject]@{
        Status = 'stopped'
        Running = $false
        Healthy = $false
        StaleState = $true
        Pid = $statePid
        Url = [string]$state.url
        Device = $state.device
        StatePath = $paths.BackendStatePath
    }
}

$process = Get-Process -Id $statePid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    if ($RepairState) { Remove-StableAmdBackendState -Path $paths.BackendStatePath }
    return [pscustomobject]@{
        Status = 'stopped'
        Running = $false
        Healthy = $false
        StaleState = $true
        Pid = $statePid
        Url = [string]$state.url
        Device = $state.device
        StatePath = $paths.BackendStatePath
    }
}

$url = [string]$state.url
if (-not [string]::IsNullOrWhiteSpace($url) -and -not $url.EndsWith('/')) { $url += '/' }
$stats = $null
if (-not [string]::IsNullOrWhiteSpace($url)) {
    try {
        $stats = Invoke-RestMethod -Uri "${url}system_stats" -Method Get -TimeoutSec 5
    }
    catch { $stats = $null }
}

if ($null -eq $stats) {
    return [pscustomobject]@{
        Status = 'degraded'
        Running = $true
        Healthy = $false
        StaleState = $false
        Pid = $statePid
        Url = $url
        Device = $state.device
        ProcessName = $process.ProcessName
        StatePath = $paths.BackendStatePath
        StdoutLog = $state.stdoutLog
        StderrLog = $state.stderrLog
    }
}

$device = @($stats.devices) | Where-Object { [string]$_.name -match '(?i)AMD|Radeon' } | Select-Object -First 1
if ($null -eq $device) { $device = @($stats.devices) | Select-Object -First 1 }

return [pscustomobject]@{
    Status = 'running'
    Running = $true
    Healthy = $true
    StaleState = $false
    Pid = $statePid
    Url = $url
    Device = $device
    ProcessName = $process.ProcessName
    StatePath = $paths.BackendStatePath
    StdoutLog = $state.stdoutLog
    StderrLog = $state.stderrLog
}
