[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$StopTimeoutSeconds = 10
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
        WasRunning = $false
        Pid = $null
        StatePath = $paths.BackendStatePath
    }
}

$statePid = $null
try { $statePid = [int]$state.pid } catch { $statePid = $null }
if ($null -eq $statePid -or $statePid -le 0) {
    Remove-StableAmdBackendState -Path $paths.BackendStatePath
    return [pscustomobject]@{
        Status = 'stopped'
        WasRunning = $false
        Pid = $statePid
        StatePath = $paths.BackendStatePath
    }
}

$process = Get-Process -Id $statePid -ErrorAction SilentlyContinue
if ($null -eq $process) {
    Remove-StableAmdBackendState -Path $paths.BackendStatePath
    return [pscustomobject]@{
        Status = 'stopped'
        WasRunning = $false
        Pid = $statePid
        StatePath = $paths.BackendStatePath
    }
}

# Reduce PID-reuse risk: when both paths are available, only stop the process
# if it is the exact Python executable StableAMD recorded when starting it.
$recordedPython = [string]$state.pythonPath
$actualProcessPath = $null
try { $actualProcessPath = [string]$process.Path } catch { $actualProcessPath = $null }
if (-not [string]::IsNullOrWhiteSpace($recordedPython) -and -not [string]::IsNullOrWhiteSpace($actualProcessPath)) {
    $expected = [IO.Path]::GetFullPath($recordedPython).TrimEnd('\')
    $actual = [IO.Path]::GetFullPath($actualProcessPath).TrimEnd('\')
    if (-not $expected.Equals($actual, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stop PID $statePid because its executable '$actualProcessPath' does not match StableAMD state '$recordedPython'."
    }
}

Stop-Process -Id $statePid -ErrorAction SilentlyContinue
$deadline = (Get-Date).AddSeconds([Math]::Max(1, $StopTimeoutSeconds))
while ((Get-Date) -lt $deadline) {
    if ($null -eq (Get-Process -Id $statePid -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 250
}

if ($null -ne (Get-Process -Id $statePid -ErrorAction SilentlyContinue)) {
    Stop-Process -Id $statePid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 250
}

if ($null -ne (Get-Process -Id $statePid -ErrorAction SilentlyContinue)) {
    throw "StableAMD could not stop its managed backend process PID $statePid. State was preserved for diagnostics."
}

Remove-StableAmdBackendState -Path $paths.BackendStatePath

return [pscustomobject]@{
    Status = 'stopped'
    WasRunning = $true
    Pid = $statePid
    StatePath = $paths.BackendStatePath
}
