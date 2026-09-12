[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$StopTimeoutSeconds = 10,
    [switch]$BackendOnly
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot
$backendState = Read-StableAmdBackendState -Path $paths.BackendStatePath
$appState = if ($BackendOnly) { $null } else { Read-StableAmdBackendState -Path $paths.AppStatePath }

function Get-StatePid {
    param([psobject]$State)
    if ($null -eq $State) { return $null }
    try {
        $value = [int]$State.pid
        if ($value -gt 0) { return $value }
    }
    catch { }
    return $null
}

function Get-ProcessSnapshot {
    try {
        return @(Get-CimInstance Win32_Process -ErrorAction Stop)
    }
    catch {
        try { return @(Get-WmiObject Win32_Process -ErrorAction Stop) }
        catch { return @() }
    }
}

function Test-RecordedPython {
    param(
        [int]$Pid,
        [psobject]$State
    )

    if ($Pid -le 0 -or $null -eq $State) { return }
    $process = Get-Process -Id $Pid -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }

    $recordedPython = [string]$State.pythonPath
    $actualProcessPath = $null
    try { $actualProcessPath = [string]$process.Path } catch { $actualProcessPath = $null }
    if ([string]::IsNullOrWhiteSpace($recordedPython) -or [string]::IsNullOrWhiteSpace($actualProcessPath)) { return }

    $expected = [IO.Path]::GetFullPath($recordedPython).TrimEnd('\')
    $actual = [IO.Path]::GetFullPath($actualProcessPath).TrimEnd('\')
    if (-not $expected.Equals($actual, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stop PID $Pid because its executable '$actualProcessPath' does not match StableAMD state '$recordedPython'."
    }
}

function Add-ProcessTree {
    param(
        [int]$RootPid,
        [object[]]$Snapshot,
        [System.Collections.Generic.HashSet[int]]$Target
    )

    if ($RootPid -le 0 -or -not $Target.Add($RootPid)) { return }
    foreach ($child in @($Snapshot | Where-Object { [int]$_.ParentProcessId -eq $RootPid })) {
        Add-ProcessTree -RootPid ([int]$child.ProcessId) -Snapshot $Snapshot -Target $Target
    }
}

function Stop-ProcessSet {
    param(
        [int[]]$Pids,
        [int]$TimeoutSeconds
    )

    $existing = @($Pids | Where-Object { $_ -gt 0 -and $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) } | Select-Object -Unique)
    if ($existing.Count -eq 0) { return @() }

    # Stop descendants before their parent processes. PowerShell process IDs are
    # not ordered by ancestry, but reversing the discovered tree set handles the
    # common StableAMD case and every PID is verified again below.
    foreach ($pidToStop in @($existing | Sort-Object -Descending)) {
        Stop-Process -Id $pidToStop -ErrorAction SilentlyContinue
    }

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    do {
        $remaining = @($existing | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)

    $remaining = @($existing | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
    foreach ($pidToStop in $remaining) {
        Stop-Process -Id $pidToStop -Force -ErrorAction SilentlyContinue
    }
    if ($remaining.Count -gt 0) { Start-Sleep -Milliseconds 300 }

    $stillRunning = @($existing | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
    if ($stillRunning.Count -gt 0) {
        throw "StableAMD could not stop managed process PID(s): $($stillRunning -join ', '). State was preserved for diagnostics."
    }

    return $existing
}

$backendPid = Get-StatePid -State $backendState
$appPid = Get-StatePid -State $appState
if ($null -ne $backendPid) { Test-RecordedPython -Pid $backendPid -State $backendState }
if ($null -ne $appPid) { Test-RecordedPython -Pid $appPid -State $appState }

$snapshot = Get-ProcessSnapshot
$backendRoots = New-Object 'System.Collections.Generic.HashSet[int]'
$appRoots = New-Object 'System.Collections.Generic.HashSet[int]'
if ($null -ne $backendPid) { [void]$backendRoots.Add($backendPid) }
if ($null -ne $appPid) { [void]$appRoots.Add($appPid) }

# Recover processes left by older StableAMD builds that did not persist the
# application PID. Matching is deliberately scoped to this repository path and
# StableAMD's two Python entry points so unrelated Python processes are untouched.
$repoPattern = [regex]::Escape($RepoRoot.TrimEnd('\'))
foreach ($entry in $snapshot) {
    $commandLine = [string]$entry.CommandLine
    if ([string]::IsNullOrWhiteSpace($commandLine) -or $commandLine -notmatch $repoPattern) { continue }
    if ($commandLine -match '(?i)run_comfy_isolated\.py') {
        [void]$backendRoots.Add([int]$entry.ProcessId)
    }
    if (-not $BackendOnly -and $commandLine -match '(?i)stableamd_server\.py') {
        [void]$appRoots.Add([int]$entry.ProcessId)
    }
}

$appTree = New-Object 'System.Collections.Generic.HashSet[int]'
$backendTree = New-Object 'System.Collections.Generic.HashSet[int]'
foreach ($rootPid in $appRoots) { Add-ProcessTree -RootPid $rootPid -Snapshot $snapshot -Target $appTree }
foreach ($rootPid in $backendRoots) { Add-ProcessTree -RootPid $rootPid -Snapshot $snapshot -Target $backendTree }

$stoppedApp = @()
if (-not $BackendOnly) {
    $stoppedApp = @(Stop-ProcessSet -Pids @($appTree) -TimeoutSeconds $StopTimeoutSeconds)
}
$stoppedBackend = @(Stop-ProcessSet -Pids @($backendTree) -TimeoutSeconds $StopTimeoutSeconds)

# A terminated ComfyUI process releases its ROCm allocations at process exit;
# remove state only after the process tree is confirmed gone.
Remove-StableAmdBackendState -Path $paths.BackendStatePath
if (-not $BackendOnly) {
    Remove-StableAmdBackendState -Path $paths.AppStatePath
}

return [pscustomobject]@{
    Status = 'stopped'
    WasRunning = (($stoppedApp.Count + $stoppedBackend.Count) -gt 0)
    BackendOnly = [bool]$BackendOnly
    BackendPid = $backendPid
    AppPid = $appPid
    StoppedBackendPids = @($stoppedBackend)
    StoppedAppPids = @($stoppedApp)
    BackendStatePath = $paths.BackendStatePath
    AppStatePath = $paths.AppStatePath
}
