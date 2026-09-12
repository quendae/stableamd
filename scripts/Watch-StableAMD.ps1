[CmdletBinding()]
param(
    [string]$RepoRoot = '',
    [int]$Tail = 30,
    [int]$PollMilliseconds = 120
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = [IO.Path]::GetFullPath($RepoRoot)
$PollMilliseconds = [Math]::Max(50, $PollMilliseconds)

Import-Module (Join-Path $PSScriptRoot 'StableAmd.Runtime.psm1') -Force
$paths = Get-StableAmdRuntimePaths -RepoRoot $RepoRoot

Write-Host ''
Write-Host 'StableAMD live diagnostics' -ForegroundColor Cyan

$script:logEntries = @()
$script:lastBackendPid = $null
$script:lastAppPid = $null

function Add-StableAmdLogEntry {
    param(
        [psobject]$State,
        [string]$PropertyName,
        [string]$Label,
        [switch]$Announce
    )

    if ($null -eq $State) { return $false }
    $property = $State.PSObject.Properties[$PropertyName]
    if ($null -eq $property) { return $false }
    $path = [string]$property.Value
    if ([string]::IsNullOrWhiteSpace($path) -or -not (Test-Path $path -PathType Leaf)) { return $false }
    if (@($script:logEntries | Where-Object { $_.Path -eq $path }).Count -gt 0) { return $false }

    $entry = [pscustomobject]@{
        Path = $path
        Label = $Label
        Position = [long]0
        Pending = ''
    }

    # A newly discovered file may already contain backend startup output. Show a
    # compact tail once, then continue from EOF so a refresh does not dump an
    # entire historical log into the supervisor terminal.
    $tailLines = @(Get-Content -LiteralPath $path -Tail ([Math]::Max(0, $Tail)) -ErrorAction SilentlyContinue)
    if ($Announce) {
        Write-Host ("[watcher] New log source: [{0}] {1}" -f $Label, $path) -ForegroundColor DarkCyan
    }
    foreach ($line in $tailLines) {
        if (-not [string]::IsNullOrWhiteSpace([string]$line)) {
            Write-Host ("[{0}] {1}" -f $Label, $line)
        }
    }
    try {
        $entry.Position = [long](Get-Item -LiteralPath $path -ErrorAction Stop).Length
    }
    catch {
        $entry.Position = 0
    }

    $script:logEntries += $entry
    return $true
}

function Sync-StableAmdTrackedLogs {
    param([switch]$Initial)

    $backend = Read-StableAmdBackendState -Path $paths.BackendStatePath
    $app = Read-StableAmdBackendState -Path $paths.AppStatePath

    if ($null -ne $backend) {
        $backendPid = [int]$backend.pid
        if ($null -eq $script:lastBackendPid) {
            $script:lastBackendPid = $backendPid
            if ($Initial) {
                Write-Host "Compute backend PID: $backendPid" -ForegroundColor Green
                Write-Host "Compute backend URL: $($backend.url)" -ForegroundColor DarkGray
            }
        }
        elseif ($script:lastBackendPid -ne $backendPid) {
            Write-Host ("[watcher] Backend restarted / refreshed: PID {0} -> {1}" -f $script:lastBackendPid, $backendPid) -ForegroundColor Yellow
            $script:lastBackendPid = $backendPid
        }

        Add-StableAmdLogEntry -State $backend -PropertyName 'stdoutLog' -Label 'backend stdout' -Announce:(-not $Initial) | Out-Null
        Add-StableAmdLogEntry -State $backend -PropertyName 'stderrLog' -Label 'backend stderr' -Announce:(-not $Initial) | Out-Null
    }
    elseif ($Initial) {
        Write-Host 'Compute backend state: not running / not tracked' -ForegroundColor Yellow
    }

    if ($null -ne $app) {
        $appPid = [int]$app.pid
        if ($null -eq $script:lastAppPid) {
            $script:lastAppPid = $appPid
            if ($Initial) {
                Write-Host "Application PID: $appPid" -ForegroundColor Green
                Write-Host "Application URL: $($app.url)" -ForegroundColor DarkGray
            }
        }
        elseif ($script:lastAppPid -ne $appPid) {
            Write-Host ("[watcher] Application restarted: PID {0} -> {1}" -f $script:lastAppPid, $appPid) -ForegroundColor Yellow
            $script:lastAppPid = $appPid
        }

        Add-StableAmdLogEntry -State $app -PropertyName 'stdoutLog' -Label 'app stdout' -Announce:(-not $Initial) | Out-Null
        Add-StableAmdLogEntry -State $app -PropertyName 'stderrLog' -Label 'app stderr' -Announce:(-not $Initial) | Out-Null
    }
    elseif ($Initial) {
        Write-Host 'Application state: not running / not tracked' -ForegroundColor Yellow
    }
}

Sync-StableAmdTrackedLogs -Initial

if ($logEntries.Count -eq 0) {
    throw 'No active StableAMD log files were found. Start StableAMD first.'
}

Write-Host ''
Write-Host 'Watching all logs concurrently (Ctrl+C stops the supervisor and releases VRAM):' -ForegroundColor Cyan
foreach ($entry in $logEntries) {
    Write-Host ("  [{0}] {1}" -f $entry.Label, $entry.Path) -ForegroundColor DarkGray
}
Write-Host ''

$utf8 = New-Object System.Text.UTF8Encoding($false, $false)

# Poll all known files by byte offset. On every pass also reread the runtime
# state files so an in-app backend refresh can switch to a new PID and new log
# files without leaving the launcher attached to stale logs.
while ($true) {
    try {
        Sync-StableAmdTrackedLogs
    }
    catch {
        # State files are briefly absent/replaced during restart. Keep the
        # supervisor alive and retry on the next poll.
    }

    foreach ($entry in @($logEntries)) {
        try {
            $info = Get-Item -LiteralPath $entry.Path -ErrorAction Stop
            $length = [long]$info.Length
            if ($length -lt [long]$entry.Position) {
                $entry.Position = 0
                $entry.Pending = ''
            }
            if ($length -le [long]$entry.Position) { continue }

            $stream = [IO.File]::Open(
                $entry.Path,
                [IO.FileMode]::Open,
                [IO.FileAccess]::Read,
                [IO.FileShare]::ReadWrite
            )
            try {
                [void]$stream.Seek([long]$entry.Position, [IO.SeekOrigin]::Begin)
                while ($stream.Position -lt $stream.Length) {
                    $remaining = [long]($stream.Length - $stream.Position)
                    $chunkSize = [int][Math]::Min(65536, $remaining)
                    if ($chunkSize -le 0) { break }

                    $buffer = New-Object byte[] $chunkSize
                    $read = $stream.Read($buffer, 0, $buffer.Length)
                    if ($read -le 0) { break }

                    $entry.Position = [long]$stream.Position
                    $entry.Pending += $utf8.GetString($buffer, 0, $read)

                    # ComfyUI/tqdm refreshes one terminal line with CR while
                    # ordinary Python logs use LF/CRLF. Treat all three as an
                    # event boundary so every sampling update is visible.
                    $parts = @([regex]::Split([string]$entry.Pending, "`r`n|`n|`r"))
                    $hasTerminator = ([string]$entry.Pending -match "(`r`n|`n|`r)$")
                    $emitCount = if ($hasTerminator) { $parts.Count } else { [Math]::Max(0, $parts.Count - 1) }

                    for ($i = 0; $i -lt $emitCount; $i++) {
                        $line = [string]$parts[$i]
                        if (-not [string]::IsNullOrWhiteSpace($line)) {
                            Write-Host ("[{0}] {1}" -f $entry.Label, $line)
                        }
                    }

                    if ($hasTerminator) {
                        $entry.Pending = ''
                    }
                    elseif ($parts.Count -gt 0) {
                        $entry.Pending = [string]$parts[$parts.Count - 1]
                    }
                }
            }
            finally {
                $stream.Dispose()
            }
        }
        catch {
            # Old logs can disappear after a backend restart. Their absence is
            # harmless because Sync-StableAmdTrackedLogs follows the new state.
        }
    }

    Start-Sleep -Milliseconds $PollMilliseconds
}
