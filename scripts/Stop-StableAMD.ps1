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

function Get-SnapshotProcessId {
    param([object]$Entry)

    if ($null -eq $Entry) { return $null }
    foreach ($propertyName in @('ProcessId', 'Id')) {
        $property = $Entry.PSObject.Properties[$propertyName]
        if ($null -eq $property) { continue }
        try {
            $value = [int]$property.Value
            if ($value -gt 0) { return $value }
        }
        catch { }
    }
    return $null
}

function Get-SnapshotParentProcessId {
    param([object]$Entry)

    if ($null -eq $Entry) { return 0 }
    foreach ($propertyName in @('ParentProcessId', 'ParentId')) {
        $property = $Entry.PSObject.Properties[$propertyName]
        if ($null -eq $property) { continue }
        try { return [int]$property.Value } catch { }
    }
    return 0
}

function Test-RecordedPython {
    param(
        [int]$ProcessId,
        [psobject]$State
    )

    if ($ProcessId -le 0 -or $null -eq $State) { return }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return }

    $recordedPython = [string]$State.pythonPath
    $actualProcessPath = $null
    try { $actualProcessPath = [string]$process.Path } catch { $actualProcessPath = $null }
    if ([string]::IsNullOrWhiteSpace($recordedPython) -or [string]::IsNullOrWhiteSpace($actualProcessPath)) { return }

    $expected = [IO.Path]::GetFullPath($recordedPython).TrimEnd('\')
    $actual = [IO.Path]::GetFullPath($actualProcessPath).TrimEnd('\')
    if (-not $expected.Equals($actual, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stop PID $ProcessId because its executable '$actualProcessPath' does not match StableAMD state '$recordedPython'."
    }
}

function Get-StableAmdManagedProcesses {
    param(
        [object[]]$Snapshot,
        [switch]$BackendOnlySearch
    )

    $repoPattern = [regex]::Escape($RepoRoot.TrimEnd('\'))
    $matches = @()
    foreach ($entry in @($Snapshot)) {
        $processId = Get-SnapshotProcessId -Entry $entry
        if ($null -eq $processId) { continue }

        $commandLineProperty = $entry.PSObject.Properties['CommandLine']
        $commandLine = if ($null -ne $commandLineProperty) { [string]$commandLineProperty.Value } else { '' }
        if ([string]::IsNullOrWhiteSpace($commandLine) -or $commandLine -notmatch $repoPattern) { continue }

        $role = $null
        if ($commandLine -match '(?i)run_comfy_isolated\.py|[\\/]ComfyUI[\\/]main\.py') {
            $role = 'backend'
        }
        elseif (-not $BackendOnlySearch -and $commandLine -match '(?i)stableamd_server\.py') {
            $role = 'application'
        }
        if ($null -eq $role) { continue }

        $nameProperty = $entry.PSObject.Properties['Name']
        $matches += [pscustomobject]@{
            ProcessId = [int]$processId
            ParentProcessId = [int](Get-SnapshotParentProcessId -Entry $entry)
            Role = $role
            Name = if ($null -ne $nameProperty) { [string]$nameProperty.Value } else { '' }
            CommandLine = $commandLine
        }
    }

    # Return individual process records, never the collection object itself.
    # A Generic.List wrapped in @() can be observed as one object by callers,
    # which previously produced an empty "PID ." diagnostic and prevented kill.
    return $matches
}

function Invoke-TaskKillTree {
    param([int]$ProcessId)

    if ($ProcessId -le 0 -or $null -eq (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        return
    }

    # Windows taskkill /T follows the real process tree at kill time. This is
    # stronger than taking one WMI snapshot and is important for ROCm/ComfyUI:
    # any helper process that survives the parent can keep the GPU allocation.
    try {
        & taskkill.exe /PID $ProcessId /T /F 2>&1 | Out-Null
    }
    catch {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Wait-ProcessesGone {
    param(
        [int[]]$ProcessIds,
        [int]$TimeoutSeconds
    )

    $ids = @($ProcessIds | Where-Object { $_ -gt 0 } | Select-Object -Unique)
    if ($ids.Count -eq 0) { return @() }

    $deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
    do {
        $remaining = @($ids | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
        if ($remaining.Count -eq 0) { return @() }
        Start-Sleep -Milliseconds 200
    } while ((Get-Date) -lt $deadline)

    return @($ids | Where-Object { $null -ne (Get-Process -Id $_ -ErrorAction SilentlyContinue) })
}

function Format-StableAmdProcessDiagnostics {
    param([object[]]$Processes)

    $rows = @($Processes | Where-Object { $null -ne $_ -and [int]$_.ProcessId -gt 0 })
    if ($rows.Count -eq 0) {
        return 'StableAMD teardown is incomplete, but no valid process identity was available. State was preserved for diagnostics.'
    }

    $lines = @(
        'StableAMD teardown is incomplete; managed process(es) still running:',
        'PID      PPID     Role         Name',
        '-------- -------- ------------ ------------------------------'
    )
    foreach ($entry in $rows) {
        $lines += ('{0,-8} {1,-8} {2,-12} {3}' -f [int]$entry.ProcessId, [int]$entry.ParentProcessId, [string]$entry.Role, [string]$entry.Name)
        if (-not [string]::IsNullOrWhiteSpace([string]$entry.CommandLine)) {
            $lines += ('         CommandLine: {0}' -f [string]$entry.CommandLine)
        }
    }
    $lines += 'State was preserved for diagnostics.'
    return ($lines -join [Environment]::NewLine)
}

$backendPid = Get-StatePid -State $backendState
$appPid = Get-StatePid -State $appState
if ($null -ne $backendPid) { Test-RecordedPython -ProcessId $backendPid -State $backendState }
if ($null -ne $appPid) { Test-RecordedPython -ProcessId $appPid -State $appState }

$initialSnapshot = Get-ProcessSnapshot
$managed = @(Get-StableAmdManagedProcesses -Snapshot $initialSnapshot -BackendOnlySearch:$BackendOnly)
$backendIds = New-Object 'System.Collections.Generic.HashSet[int]'
$appIds = New-Object 'System.Collections.Generic.HashSet[int]'
if ($null -ne $backendPid) { [void]$backendIds.Add($backendPid) }
if ($null -ne $appPid) { [void]$appIds.Add($appPid) }
foreach ($entry in $managed) {
    if ($entry.Role -eq 'backend') { [void]$backendIds.Add([int]$entry.ProcessId) }
    elseif (-not $BackendOnly -and $entry.Role -eq 'application') { [void]$appIds.Add([int]$entry.ProcessId) }
}

# Stop the application first so it cannot start/restart compute work while the
# backend is being torn down. BackendOnly intentionally leaves the app alive.
if (-not $BackendOnly) {
    foreach ($processId in @($appIds)) { Invoke-TaskKillTree -ProcessId $processId }
}
foreach ($processId in @($backendIds)) { Invoke-TaskKillTree -ProcessId $processId }

$requestedIds = @()
if (-not $BackendOnly) { $requestedIds += @($appIds) }
$requestedIds += @($backendIds)
$remainingRequested = @(Wait-ProcessesGone -ProcessIds $requestedIds -TimeoutSeconds $StopTimeoutSeconds)
if ($remainingRequested.Count -gt 0) {
    foreach ($processId in $remainingRequested) { Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
}

# Final repo-scoped sweep. This catches an orphan created by an older build or
# a helper that became detached from the original process tree. We deliberately
# require both this repository path and a StableAMD entry point in CommandLine.
$postSnapshot = Get-ProcessSnapshot
$postManaged = @(Get-StableAmdManagedProcesses -Snapshot $postSnapshot -BackendOnlySearch:$BackendOnly)
foreach ($entry in $postManaged) {
    Invoke-TaskKillTree -ProcessId ([int]$entry.ProcessId)
}
if ($postManaged.Count -gt 0) { Start-Sleep -Milliseconds 700 }

$finalSnapshot = Get-ProcessSnapshot
$stillManaged = @(Get-StableAmdManagedProcesses -Snapshot $finalSnapshot -BackendOnlySearch:$BackendOnly)
if ($stillManaged.Count -gt 0) {
    throw (Format-StableAmdProcessDiagnostics -Processes $stillManaged)
}

# A terminated ComfyUI process cannot retain its ROCm allocation. Remove state
# only after the repo-scoped process verification above confirms it is gone.
Remove-StableAmdBackendState -Path $paths.BackendStatePath
if (-not $BackendOnly) {
    Remove-StableAmdBackendState -Path $paths.AppStatePath
}

return [pscustomobject]@{
    Status = 'stopped'
    WasRunning = (($requestedIds.Count + $managed.Count) -gt 0)
    BackendOnly = [bool]$BackendOnly
    BackendPid = $backendPid
    AppPid = $appPid
    TargetBackendPids = @($backendIds)
    TargetAppPids = if ($BackendOnly) { @() } else { @($appIds) }
    RemainingManagedProcesses = @()
    BackendStatePath = $paths.BackendStatePath
    AppStatePath = $paths.AppStatePath
}
